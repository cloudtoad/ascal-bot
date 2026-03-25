"""Per-invocation and per-session context objects."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nio import AsyncClient, MatrixRoom

    from bot.config import AppConfig
    from bot.dispatcher import Dispatcher
    from bot.messaging import Messenger
    from bot.notifications import NotificationBus
    from bot.user_settings import get_user_location, set_user_location


@dataclass
class CommandContext:
    """Context passed to command handlers."""

    room_id: str
    sender: str
    command: str
    args: list[str]
    raw_body: str
    event_id: str
    _messenger: Messenger

    async def respond(self, markdown: str) -> None:
        """Send a markdown reply to the room where the command was issued."""
        await self._messenger.send_markdown(self.room_id, markdown)


@dataclass
class EventContext:
    """Context passed to event handlers."""

    room: MatrixRoom
    event: object
    client: AsyncClient
    _messenger: Messenger

    async def respond(self, markdown: str) -> None:
        """Send a markdown reply to the room where the event occurred."""
        await self._messenger.send_markdown(self.room.room_id, markdown)


@dataclass
class BotContext:
    """Shared context available to all modules during setup and runtime."""

    client: AsyncClient
    config: AppConfig
    dispatcher: Dispatcher
    messenger: Messenger
    notifications: NotificationBus
    user_settings: object  # bot.user_settings module
    logger_factory: _LoggerFactory


class _LoggerFactory:
    """Creates module-scoped loggers under the bot.modules.* namespace."""

    def get_logger(self, module_name: str) -> logging.Logger:
        return logging.getLogger(f"bot.modules.{module_name}")
