"""Messaging utilities for sending text, markdown, and DMs via Matrix."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import markdown as md
from nio.exceptions import OlmUnverifiedDeviceError

if TYPE_CHECKING:
    from nio import AsyncClient

log = logging.getLogger(__name__)


class Messenger:
    """High-level message sending interface wrapping the nio AsyncClient."""

    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    async def send_markdown(self, room_id: str, text: str) -> None:
        """Render markdown to HTML and send as a formatted message."""
        html = md.markdown(text, extensions=["fenced_code", "nl2br"])
        content = {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": html,
        }
        await self._send(room_id, content)

    async def send_text(self, room_id: str, text: str) -> None:
        """Send a plain-text message."""
        content = {
            "msgtype": "m.text",
            "body": text,
        }
        await self._send(room_id, content)

    async def send_dm(self, user_id: str, text: str) -> None:
        """Find or create a DM room with *user_id* and send a markdown message."""
        room_id = await self._find_dm_room(user_id)
        if room_id is None:
            room_id = await self._create_dm_room(user_id)
        if room_id is None:
            log.error("Could not create DM room for %s", user_id)
            return
        await self.send_markdown(room_id, text)

    # ── Internals ────────────────────────────────────────────────────────

    async def _send(self, room_id: str, content: dict) -> None:
        """Send a room event, handling OlmUnverifiedDeviceError by trusting."""
        try:
            await self._client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
                ignore_unverified_devices=True,
            )
        except OlmUnverifiedDeviceError:
            # Trust all unverified devices in the room, then retry
            log.warning(
                "OlmUnverifiedDeviceError in %s — trusting devices and retrying",
                room_id,
            )
            await self._trust_room_devices(room_id)
            await self._client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
                ignore_unverified_devices=True,
            )

    async def _trust_room_devices(self, room_id: str) -> None:
        """Trust all unverified devices for users in a room."""
        room = self._client.rooms.get(room_id)
        if room is None:
            return
        for user_id in room.users:
            for device_id, device in self._client.olm.device_store.get(
                user_id, {}
            ).items():
                if not (
                    self._client.olm.is_device_verified(device)
                    or self._client.olm.is_device_blacklisted(device)
                ):
                    self._client.olm.verify_device(device)
                    log.debug("Trusted device %s for %s", device_id, user_id)

    async def _find_dm_room(self, user_id: str) -> str | None:
        """Look for an existing DM room with *user_id*."""
        for room_id, room in self._client.rooms.items():
            # A DM room typically has exactly 2 members (us and the target)
            members = list(room.users.keys())
            if len(members) == 2 and user_id in members:
                # Check if it looks like a direct room (small, no name set by user)
                if room.member_count <= 2:
                    return room_id
        return None

    async def _create_dm_room(self, user_id: str) -> str | None:
        """Create a new DM room with *user_id*."""
        from nio import RoomCreateResponse

        resp = await self._client.room_create(
            invite=[user_id],
            is_direct=True,
        )
        if isinstance(resp, RoomCreateResponse):
            log.info("Created DM room %s for %s", resp.room_id, user_id)
            return resp.room_id
        log.error("Failed to create DM room for %s: %s", user_id, resp)
        return None
