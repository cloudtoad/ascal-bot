"""Notification bus for publishing alerts to admins and mod rooms."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.config import AppConfig
    from bot.messaging import Messenger

log = logging.getLogger(__name__)


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# Level prefixes for formatting alerts
_LEVEL_PREFIX = {
    AlertLevel.INFO: "INFO",
    AlertLevel.WARNING: "WARNING",
    AlertLevel.ERROR: "ERROR",
}


@dataclass
class Alert:
    """A notification to be delivered to admins."""

    level: AlertLevel
    source: str  # module name that produced the alert
    summary: str
    details: str = ""
    room_id: str | None = None  # optional room context


class NotificationBus:
    """Publishes alerts to the mod room (if configured) and DMs to admin users."""

    def __init__(self, messenger: "Messenger", config: "AppConfig") -> None:
        self._messenger = messenger
        self._mod_room_id: str | None = (
            config.moderation.mod_room_id if config.moderation.mod_room_id else None
        )
        self._admin_users: list[str] = config.notifications.admin_users

    async def publish(self, alert: Alert) -> None:
        """Send an alert to all configured destinations."""
        prefix = _LEVEL_PREFIX.get(alert.level, "ALERT")
        lines = [
            f"**[{prefix}]** {alert.summary}",
            f"*Source: {alert.source}*",
        ]
        if alert.room_id:
            lines.append(f"*Room: {alert.room_id}*")
        if alert.details:
            lines.append("")
            lines.append(alert.details)

        message = "\n".join(lines)

        # Send to mod room
        if self._mod_room_id:
            try:
                await self._messenger.send_markdown(self._mod_room_id, message)
            except Exception:
                log.exception("Failed to send alert to mod room %s", self._mod_room_id)

        # DM each admin user
        for user_id in self._admin_users:
            try:
                await self._messenger.send_dm(user_id, message)
            except Exception:
                log.exception("Failed to DM alert to %s", user_id)
