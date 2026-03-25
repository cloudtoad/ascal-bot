"""
Moderation module for IngwineBot.

Tiered trust model:
  1. Power level > 0  → always trusted, skip all checks
  2. Message count >= threshold → trusted, skip all checks
  3. New user + image/video/file → auto-redact + mod alert
  4. New user + bare link → auto-redact + mod alert
  5. New user + text → Claude analysis → flag if spam/hate/harassment

Mod room commands:
  !mod ban @user:server          — ban from all protected rooms
  !mod kick @user:server [room]  — kick from a room (defaults to first protected)
  !mod trust @user:server        — mark trusted in all protected rooms
  !mod status @user:server       — show message count and trust status
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from anthropic import Anthropic

from bot.context import BotContext, CommandContext
from bot.notifications import Alert, AlertLevel

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MEDIA_MSGTYPES = {"m.image", "m.video", "m.file", "m.audio", "m.sticker"}
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
STATE_FILE = Path("mod_state.json")


# ── State persistence ────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"counts": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _get_count(state: dict, room_id: str, user_id: str) -> int:
    return state["counts"].get(room_id, {}).get(user_id, 0)


def _increment_count(state: dict, room_id: str, user_id: str) -> None:
    state["counts"].setdefault(room_id, {})
    state["counts"][room_id][user_id] = _get_count(state, room_id, user_id) + 1
    _save_state(state)


def _set_count(state: dict, room_id: str, user_id: str, value: int) -> None:
    state["counts"].setdefault(room_id, {})
    state["counts"][room_id][user_id] = value
    _save_state(state)


# ── Message checks ───────────────────────────────────────────────────────────

def _is_media(event) -> bool:
    return getattr(event, "msgtype", None) in MEDIA_MSGTYPES


def _is_bare_link(event) -> bool:
    if getattr(event, "msgtype", None) != "m.text":
        return False
    body = getattr(event, "body", "") or ""
    urls = URL_RE.findall(body)
    if not urls:
        return False
    stripped = URL_RE.sub("", body).strip()
    return len(stripped) < 20


# ── Claude analysis ──────────────────────────────────────────────────────────

async def _analyze(anthropic_client: Anthropic, text: str, user_id: str) -> tuple[bool, str]:
    """Return (should_flag, reason)."""
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are a moderation assistant for Ingwine Heathenship, "
                        "a Germanic heathen religious community on Matrix. "
                        "Analyze this message from a new (unverified) user.\n\n"
                        "Reply with JSON only, no other text: "
                        "{\"flag\": true/false, \"reason\": \"brief reason or ok\"}\n\n"
                        "Flag: spam, hate speech, slurs used hatefully, targeted harassment, "
                        "promotional content (pills, crypto, adult services).\n"
                        "Do NOT flag: casual profanity in conversation, questions about "
                        "heathenry/Norse/Germanic topics, religious discussion, strong opinions. "
                        "When uncertain, do NOT flag — moderators handle edge cases.\n\n"
                        f"User: {user_id}\n"
                        f"Message: {text}"
                    ),
                }
            ],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)
        return bool(result.get("flag")), str(result.get("reason", "ok"))
    except Exception as exc:
        log.warning("Claude analysis failed: %s", exc)
        return False, "analysis error — skipped"


# ── Power level helper ───────────────────────────────────────────────────────

async def _get_power_level(client, room_id: str, user_id: str) -> int:
    try:
        resp = await client.room_get_state_event(room_id, "m.room.power_levels", "")
        content = getattr(resp, "content", {}) or {}
        users = content.get("users", {})
        return int(users.get(user_id, content.get("users_default", 0)))
    except Exception:
        return 0


# ── Module class ─────────────────────────────────────────────────────────────

class ModerationModule:
    """Tiered trust moderation with Claude-powered text analysis."""

    name = "moderation"

    def __init__(self) -> None:
        self._client = None
        self._messenger = None
        self._notifications = None
        self._anthropic = None
        self._state: dict = {}
        self._mod_room_id: str = ""
        self._protected_rooms: list[str] = []
        self._threshold: int = 5
        self._bot_user_id: str = ""

    async def setup(self, ctx: BotContext) -> None:
        mc = ctx.config.moderation
        if not mc.enabled:
            log.info("Moderation module disabled (set [moderation] enabled = true to activate)")
            return

        self._client = ctx.client
        self._messenger = ctx.messenger
        self._notifications = ctx.notifications
        self._mod_room_id = mc.mod_room_id
        self._protected_rooms = mc.protected_rooms
        self._threshold = mc.new_user_threshold
        self._bot_user_id = ctx.client.user_id
        self._anthropic = Anthropic(api_key=mc.anthropic_api_key)
        self._state = _load_state()

        # Register as raw message handler (sees ALL messages before command parsing)
        ctx.dispatcher.register_raw_message_handler(self._on_any_message)

        # Register !mod command (hidden from help)
        ctx.dispatcher.register_command("mod", self._cmd_mod)

        log.info(
            "Moderation active — protecting %d room(s), threshold=%d, mod room=%s",
            len(self._protected_rooms),
            self._threshold,
            self._mod_room_id,
        )

    async def teardown(self) -> None:
        pass

    # ── Raw message handler ──────────────────────────────────────────────

    async def _on_any_message(self, room, message) -> None:
        room_id: str = room.room_id
        sender: str = message.sender

        if sender == self._bot_user_id:
            return

        # Protected room moderation
        if room_id not in self._protected_rooms:
            return

        # Power level > 0 → always trusted
        power = await _get_power_level(self._client, room_id, sender)
        if power > 0:
            _increment_count(self._state, room_id, sender)
            return

        msg_count = _get_count(self._state, room_id, sender)

        # Past threshold → trusted
        if msg_count >= self._threshold:
            _increment_count(self._state, room_id, sender)
            return

        # ── New user checks ──────────────────────────────────────────────
        flagged = False
        reason = ""
        auto_redact = False

        if _is_media(message):
            flagged = True
            reason = "New user posted media before reaching trust threshold"
            auto_redact = True

        elif _is_bare_link(message):
            flagged = True
            reason = "New user posted bare link before reaching trust threshold"
            auto_redact = True

        elif getattr(message, "msgtype", None) == "m.text":
            text = getattr(message, "body", "") or ""
            if text:
                flagged, reason = await _analyze(self._anthropic, text, sender)
                if flagged:
                    auto_redact = True

        if flagged:
            if auto_redact:
                try:
                    event_id = getattr(message, "event_id", None)
                    if event_id:
                        await self._client.room_redact(room_id, event_id, reason=reason)
                    else:
                        log.warning("No event_id on message, cannot redact")
                        auto_redact = False
                except Exception as exc:
                    log.warning("Redact failed: %s", exc)
                    auto_redact = False

            await self._send_mod_alert(room_id, message, sender, reason, auto_redact, msg_count)
        else:
            _increment_count(self._state, room_id, sender)

    # ── Mod commands ─────────────────────────────────────────────────────

    async def _cmd_mod(self, ctx: CommandContext) -> None:
        # Only respond in the mod room
        if ctx.room_id != self._mod_room_id:
            return

        if len(ctx.args) < 2:
            await ctx.respond(
                "Usage: `!mod ban|kick|trust|status @user:server [room_id]`"
            )
            return

        command = ctx.args[0]
        target_user = ctx.args[1]
        extra = ctx.args[2:]

        try:
            if command == "ban":
                for pid in self._protected_rooms:
                    await self._client.room_ban(pid, target_user, reason="Banned via mod room")
                await ctx.respond(f"Banned **{target_user}** from all protected rooms.")

            elif command == "kick":
                kick_room = extra[0] if extra else self._protected_rooms[0]
                await self._client.room_kick(kick_room, target_user, reason="Kicked via mod room")
                await ctx.respond(f"Kicked **{target_user}** from `{kick_room}`.")

            elif command == "trust":
                for pid in self._protected_rooms:
                    _set_count(self._state, pid, target_user, self._threshold + 1)
                await ctx.respond(f"**{target_user}** is now trusted in all protected rooms.")

            elif command == "status":
                lines = [f"**Status for {target_user}:**"]
                for pid in self._protected_rooms:
                    c = _get_count(self._state, pid, target_user)
                    trusted = "trusted" if c >= self._threshold else f"{c}/{self._threshold} messages"
                    lines.append(f"- `{pid}`: {trusted}")
                await ctx.respond("\n".join(lines))

            else:
                await ctx.respond(
                    "Unknown command. Available: `!mod ban|kick|trust|status @user:server [room_id]`"
                )

        except Exception as exc:
            log.exception("Mod command error")
            await ctx.respond(f"Error: {exc}")

    # ── Alert formatting ─────────────────────────────────────────────────

    async def _send_mod_alert(
        self,
        room_id: str,
        event,
        sender: str,
        reason: str,
        auto_redacted: bool,
        msg_count: int,
    ) -> None:
        body = getattr(event, "body", "[non-text content]") or "[non-text content]"
        event_id = getattr(event, "event_id", "unknown")

        summary = f"Flagged message from {sender}"
        details = "\n".join([
            f"**User:** {sender}",
            f"**Room:** {room_id}",
            f"**Messages approved so far:** {msg_count}",
            f"**Reason:** {reason}",
            f"**Auto-redacted:** {'Yes' if auto_redacted else 'No'}",
            "",
            "**Content:**",
            f"> {body[:400]}{'...' if len(body) > 400 else ''}",
            "",
            "**Commands:**",
            f"- `!mod ban {sender}`",
            f"- `!mod kick {sender} {room_id}`",
            f"- `!mod trust {sender}`",
            f"- `!mod status {sender}`",
            f"_(event: {event_id})_",
        ])

        # Publish via notification bus (goes to mod room + admin DMs)
        await self._notifications.publish(Alert(
            level=AlertLevel.WARNING,
            source=self.name,
            summary=summary,
            details=details,
            room_id=room_id,
        ))
