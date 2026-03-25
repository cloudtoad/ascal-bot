"""Central command and event router."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from nio import MatrixRoom

    from bot.context import CommandContext, EventContext
    from bot.messaging import Messenger

log = logging.getLogger(__name__)

# Type aliases for handler signatures
CommandHandler = Callable[["CommandContext"], Coroutine[Any, Any, None]]
EventHandler = Callable[["EventContext"], Coroutine[Any, Any, None]]
RawMessageHandler = Callable[["MatrixRoom", Any], Coroutine[Any, Any, None]]
FilterFn = Callable[["MatrixRoom", Any], bool]


@dataclass
class _CommandEntry:
    name: str
    handler: CommandHandler
    aliases: list[str] = field(default_factory=list)
    help_text: str | None = None


@dataclass
class _EventEntry:
    event_type: type
    handler: EventHandler
    filter_fn: FilterFn | None = None


class Dispatcher:
    """Routes incoming Matrix events to registered command and event handlers.

    Processing order for messages:
        1. All raw message handlers run first (see every message).
        2. If the message starts with the command prefix, it is parsed and
           dispatched to the matching command handler.
    """

    def __init__(self, prefix: str, messenger: "Messenger", bot_user_id: str) -> None:
        self._prefix = prefix
        self._messenger = messenger
        self._bot_user_id = bot_user_id

        self._commands: dict[str, _CommandEntry] = {}
        self._alias_map: dict[str, str] = {}
        self._event_handlers: list[_EventEntry] = []
        self._raw_message_handlers: list[RawMessageHandler] = []

    # ── Registration ─────────────────────────────────────────────────────

    def register_command(
        self,
        name: str,
        handler: CommandHandler,
        aliases: list[str] | None = None,
        help_text: str | None = None,
    ) -> None:
        """Register a command handler.

        Args:
            name: Primary command name (without prefix).
            handler: Async callable receiving a CommandContext.
            aliases: Optional alternative names for the command.
            help_text: One-line description shown in help listings.
        """
        entry = _CommandEntry(
            name=name,
            handler=handler,
            aliases=aliases or [],
            help_text=help_text,
        )
        self._commands[name] = entry
        for alias in entry.aliases:
            self._alias_map[alias] = name
        log.debug("Registered command: %s (aliases: %s)", name, entry.aliases)

    def register_event_handler(
        self,
        event_type: type,
        handler: EventHandler,
        filter_fn: FilterFn | None = None,
    ) -> None:
        """Register a handler for a specific nio event type.

        Args:
            event_type: The nio event class to match (e.g. RoomMemberEvent).
            handler: Async callable receiving an EventContext.
            filter_fn: Optional predicate; handler runs only if this returns True.
        """
        self._event_handlers.append(
            _EventEntry(event_type=event_type, handler=handler, filter_fn=filter_fn)
        )
        log.debug("Registered event handler for %s", event_type.__name__)

    def register_raw_message_handler(self, handler: RawMessageHandler) -> None:
        """Register a handler that sees ALL messages before command parsing.

        Args:
            handler: Async callable receiving (room, event).
        """
        self._raw_message_handlers.append(handler)
        log.debug("Registered raw message handler: %s", handler)

    # ── Dispatch ─────────────────────────────────────────────────────────

    async def dispatch_message(self, room: "MatrixRoom", event: Any) -> None:
        """Called by core on every RoomMessageText event."""
        sender: str = event.sender

        # Ignore our own messages
        if sender == self._bot_user_id:
            return

        # 1. Run raw message handlers first
        for handler in self._raw_message_handlers:
            try:
                await handler(room, event)
            except Exception:
                log.exception("Error in raw message handler %s", handler)

        # 2. Check for command prefix
        body: str = getattr(event, "body", "") or ""
        if not body.startswith(self._prefix):
            return

        # 3. Parse command
        stripped = body[len(self._prefix) :]
        parts = stripped.split()
        if not parts:
            return

        cmd_name = parts[0].lower()
        args = parts[1:]

        # Resolve alias
        canonical = self._alias_map.get(cmd_name, cmd_name)
        entry = self._commands.get(canonical)
        if entry is None:
            return  # Unknown command; silently ignore

        # Build context and dispatch
        from bot.context import CommandContext

        ctx = CommandContext(
            room_id=room.room_id,
            sender=sender,
            command=canonical,
            args=args,
            raw_body=body,
            event_id=event.event_id,
            _messenger=self._messenger,
        )

        try:
            await entry.handler(ctx)
        except Exception:
            log.exception("Error handling command '%s' from %s", canonical, sender)
            try:
                await ctx.respond("Something went wrong processing that command.")
            except Exception:
                log.exception("Failed to send error response")

    async def dispatch_event(self, room: "MatrixRoom", event: Any) -> None:
        """Called by core on non-message events (e.g. RoomMemberEvent)."""
        from bot.context import EventContext

        for entry in self._event_handlers:
            if not isinstance(event, entry.event_type):
                continue
            if entry.filter_fn is not None and not entry.filter_fn(room, event):
                continue
            ctx = EventContext(
                room=room,
                event=event,
                client=None,  # will be set by core if needed
                _messenger=self._messenger,
            )
            try:
                await entry.handler(ctx)
            except Exception:
                log.exception(
                    "Error in event handler for %s",
                    entry.event_type.__name__,
                )

    # ── Introspection ────────────────────────────────────────────────────

    def get_commands(self) -> list[_CommandEntry]:
        """Return all registered command entries (for help generation)."""
        return list(self._commands.values())
