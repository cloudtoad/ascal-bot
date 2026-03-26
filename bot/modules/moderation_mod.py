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

import asyncio

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

_ANALYSIS_PROMPT = (
    "You are a moderation assistant for Ingwine Heathenship, "
    "a Germanic heathen religious community on Matrix. "
    "Analyze this message from a new (unverified) user.\n\n"
    "Reply with JSON only, no other text: "
    '{"flag": true/false, "reason": "brief reason or ok"}\n\n'
    "Flag: spam, hate speech, slurs used hatefully, targeted harassment, "
    "promotional content (pills, crypto, adult services).\n"
    "Do NOT flag: casual profanity in conversation, questions about "
    "heathenry/Norse/Germanic topics, religious discussion, strong opinions. "
    "When uncertain, do NOT flag — moderators handle edge cases.\n\n"
)


async def _analyze(text: str, user_id: str) -> tuple[bool, str]:
    """Run text through claude -p for moderation analysis. Return (should_flag, reason)."""
    prompt = f"{_ANALYSIS_PROMPT}User: {user_id}\nMessage: {text}"
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--model", "haiku",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=30)
        if proc.returncode != 0:
            log.warning("claude -p failed (rc=%d): %s", proc.returncode, stderr.decode().strip())
            return False, "analysis error — skipped"
        raw = stdout.decode().strip()
        result = json.loads(raw)
        return bool(result.get("flag")), str(result.get("reason", "ok"))
    except asyncio.TimeoutError:
        log.warning("Claude analysis timed out")
        return False, "analysis timeout — skipped"
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
        self._state = _load_state()

        # Register as raw message handler (sees ALL messages before command parsing)
        ctx.dispatcher.register_raw_message_handler(self._on_any_message)

        # Register !mod command (hidden from help)
        ctx.dispatcher.register_command("mod", self._cmd_mod)
        ctx.dispatcher.register_command("analyze", self._cmd_analyze,
                                        help_text="Run moderation analysis on text (mod/DM only)")

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
                flagged, reason = await _analyze(text, sender)
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

    # ── Analyze command ───────────────────────────────────────────────────

    async def _cmd_analyze(self, ctx: CommandContext) -> None:
        """Run moderation analysis. Works in mod room or DMs.

        Usage:
            !analyze @user:server     — pull recent messages and analyze
            !analyze some text here   — analyze the provided text directly
        """
        room = self._client.rooms.get(ctx.room_id)
        is_dm = room and room.member_count <= 2
        is_mod_room = ctx.room_id == self._mod_room_id

        if not (is_dm or is_mod_room):
            return

        if not ctx.args:
            await ctx.respond(
                "Usage:\n"
                "`!analyze @user:server` — analyze a user's recent messages\n"
                "`!analyze some text here` — analyze text directly"
            )
            return

        # Check if first arg looks like a Matrix user ID
        if ctx.args[0].startswith("@") and ":" in ctx.args[0]:
            await self._analyze_user(ctx, ctx.args[0])
        else:
            text = " ".join(ctx.args)
            flagged, reason = await _analyze(text, "unknown")
            if flagged:
                await ctx.respond(f"**FLAGGED**: {reason}")
            else:
                await ctx.respond(f"**OK**: {reason}")

    async def _analyze_user(self, ctx: CommandContext, target_user: str) -> None:
        """Pull a user's recent messages from protected rooms and analyze each."""
        from nio import RoomMessagesResponse

        await ctx.respond(f"Scanning recent messages from **{target_user}**...")

        messages_found = []

        for room_id in self._protected_rooms:
            room = self._client.rooms.get(room_id)
            if room is None:
                continue

            # Get the room's prev_batch token for pagination
            start_token = room.prev_batch
            if not start_token:
                continue

            resp = await self._client.room_messages(
                room_id, start=start_token, limit=100,
            )
            if not isinstance(resp, RoomMessagesResponse):
                continue

            for event in resp.chunk:
                if getattr(event, "sender", None) != target_user:
                    continue
                body = getattr(event, "body", None)
                if not body:
                    continue
                messages_found.append((room_id, body))

        if not messages_found:
            await ctx.respond(f"No recent text messages found from **{target_user}** in protected rooms.")
            return

        lines = [f"**Analysis of {target_user}** ({len(messages_found)} messages found)", ""]
        flagged_count = 0

        for room_id, body in messages_found[:20]:  # cap at 20 to avoid hammering claude
            flagged, reason = await _analyze(body, target_user)
            if flagged:
                flagged_count += 1
                lines.append(f"**FLAGGED**: {reason}")
                lines.append(f"> {body[:200]}{'...' if len(body) > 200 else ''}")
                lines.append("")
            else:
                lines.append(f"OK: {body[:100]}{'...' if len(body) > 100 else ''}")

        lines.append("")
        lines.append(f"**Summary**: {flagged_count}/{len(messages_found[:20])} flagged")

        if flagged_count > 0:
            lines.append("")
            lines.append(f"**Commands:**")
            lines.append(f"- `!mod ban {target_user}`")
            lines.append(f"- `!mod trust {target_user}`")

        await ctx.respond("\n".join(lines))

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
