"""
Moderation module for IngwineBot.

Hooks into all room messages and applies a tiered trust model:

  1. Power level > 0  → always trusted, skip all checks
  2. Message count >= threshold → trusted, skip all checks
  3. New user + image/video/file → auto-redact + mod alert
  4. New user + bare link → auto-redact + mod alert
  5. New user + text → Claude analysis → flag if spam/hate/harassment

Mod room commands (sent as plain messages in the mod room):
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

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MEDIA_MSGTYPES = {"m.image", "m.video", "m.file", "m.audio", "m.sticker"}
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

STATE_FILE = Path("mod_state.json")


# ── State persistence ────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"counts": {}}  # {"counts": {"!room:server": {"@user:server": int}}}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_count(state: dict, room_id: str, user_id: str) -> int:
    return state["counts"].get(room_id, {}).get(user_id, 0)


def increment_count(state: dict, room_id: str, user_id: str) -> None:
    state["counts"].setdefault(room_id, {})
    state["counts"][room_id][user_id] = get_count(state, room_id, user_id) + 1
    _save_state(state)


def set_count(state: dict, room_id: str, user_id: str, value: int) -> None:
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

async def _get_power_level(async_client, room_id: str, user_id: str) -> int:
    try:
        resp = await async_client.room_get_state_event(room_id, "m.room.power_levels", "")
        content = getattr(resp, "content", {}) or {}
        users = content.get("users", {})
        return int(users.get(user_id, content.get("users_default", 0)))
    except Exception:
        return 0


# ── Mod alert ────────────────────────────────────────────────────────────────

async def _send_mod_alert(
    bot,
    mod_room_id: str,
    room_id: str,
    event,
    sender: str,
    reason: str,
    auto_redacted: bool,
    msg_count: int,
) -> None:
    body = getattr(event, "body", "[non-text content]") or "[non-text content]"
    event_id = getattr(event, "event_id", "unknown")
    lines = [
        "⚠️ **Moderation Alert**",
        "",
        f"**User:** {sender}",
        f"**Room:** {room_id}",
        f"**Messages approved so far:** {msg_count}",
        f"**Reason:** {reason}",
        f"**Auto-redacted:** {'Yes' if auto_redacted else 'No'}",
        "",
        "**Content:**",
        f"> {body[:400]}{'…' if len(body) > 400 else ''}",
        "",
        "**Commands:**",
        f"• `!mod ban {sender}`",
        f"• `!mod kick {sender} {room_id}`",
        f"• `!mod trust {sender}`",
        f"• `!mod status {sender}`",
        f"_(event: {event_id})_",
    ]
    await bot.api.send_markdown_message(mod_room_id, "\n".join(lines))


# ── Main registration function ───────────────────────────────────────────────

def register_moderation(bot, config: dict) -> None:
    """Register moderation listeners on the bot instance."""

    mc = config.get("moderation", {})
    if not mc.get("enabled", False):
        log.info("Moderation module disabled (set [moderation] enabled = true to activate)")
        return

    mod_room_id: str = mc["mod_room_id"]
    protected_rooms: list[str] = mc["protected_rooms"]
    threshold: int = int(mc.get("new_user_threshold", 5))
    anthropic_api_key: str = mc["anthropic_api_key"]

    anthropic_client = Anthropic(api_key=anthropic_api_key)
    state = _load_state()

    log.info(
        "Moderation active — protecting %d room(s), threshold=%d, mod room=%s",
        len(protected_rooms),
        threshold,
        mod_room_id,
    )

    @bot.listener.on_message_event
    async def on_any_message(room, message):
        room_id: str = room.room_id
        sender: str = message.sender
        bot_user_id = bot.async_client.user_id

        # Never process our own messages
        if sender == bot_user_id:
            return

        # ── Mod room commands ────────────────────────────────────────────────
        if room_id == mod_room_id:
            body = getattr(message, "body", "") or ""
            if not body.startswith("!mod "):
                return
            parts = body.split()
            # parts: ["!mod", command, arg1, arg2...]
            if len(parts) < 3:
                await bot.api.send_markdown_message(
                    mod_room_id,
                    "Usage: `!mod ban|kick|trust|status @user:server [room_id]`",
                )
                return

            _, command, target_user, *extra = parts

            try:
                if command == "ban":
                    for pid in protected_rooms:
                        await bot.async_client.room_ban(pid, target_user, reason="Banned via mod room")
                    await bot.api.send_markdown_message(
                        mod_room_id, f"✅ Banned **{target_user}** from all protected rooms."
                    )

                elif command == "kick":
                    kick_room = extra[0] if extra else protected_rooms[0]
                    await bot.async_client.room_kick(kick_room, target_user, reason="Kicked via mod room")
                    await bot.api.send_markdown_message(
                        mod_room_id, f"✅ Kicked **{target_user}** from `{kick_room}`."
                    )

                elif command == "trust":
                    for pid in protected_rooms:
                        set_count(state, pid, target_user, threshold + 1)
                    await bot.api.send_markdown_message(
                        mod_room_id, f"✅ **{target_user}** is now trusted in all protected rooms."
                    )

                elif command == "status":
                    lines = [f"**Status for {target_user}:**"]
                    for pid in protected_rooms:
                        c = get_count(state, pid, target_user)
                        trusted = "✅ trusted" if c >= threshold else f"⏳ {c}/{threshold} messages"
                        lines.append(f"• `{pid}`: {trusted}")
                    await bot.api.send_markdown_message(mod_room_id, "\n".join(lines))

                else:
                    await bot.api.send_markdown_message(
                        mod_room_id,
                        "Unknown command. Available: `!mod ban|kick|trust|status @user:server [room_id]`",
                    )

            except Exception as exc:
                log.exception("Mod command error")
                await bot.api.send_markdown_message(mod_room_id, f"❌ Error: {exc}")

            return  # done with mod room handling

        # ── Protected room moderation ────────────────────────────────────────
        if room_id not in protected_rooms:
            return

        # Power level > 0 → always trusted
        power = await _get_power_level(bot.async_client, room_id, sender)
        if power > 0:
            increment_count(state, room_id, sender)
            return

        msg_count = get_count(state, room_id, sender)

        # Past threshold → trusted
        if msg_count >= threshold:
            increment_count(state, room_id, sender)
            return

        # ── New user checks ──────────────────────────────────────────────────
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
                flagged, reason = await _analyze(anthropic_client, text, sender)
                if flagged:
                    auto_redact = True

        if flagged:
            if auto_redact:
                try:
                    event_id = getattr(message, "event_id", None)
                    if event_id:
                        await bot.async_client.room_redact(room_id, event_id, reason=reason)
                    else:
                        log.warning("No event_id on message, cannot redact")
                        auto_redact = False
                except Exception as exc:
                    log.warning("Redact failed: %s", exc)
                    auto_redact = False

            await _send_mod_alert(
                bot, mod_room_id, room_id, message, sender,
                reason, auto_redact, msg_count,
            )
        else:
            increment_count(state, room_id, sender)
