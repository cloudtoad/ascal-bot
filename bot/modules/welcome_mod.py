"""Welcome message module for IngwineBot."""
from __future__ import annotations

import logging

from nio.events.room_events import RoomMemberEvent

from bot.context import BotContext, EventContext

log = logging.getLogger(__name__)

WELCOME_MSG = (
    "Welcome to the Ingwine Heathenship space. "
    "This server is for people who are interested in practicing Ingwine "
    "Heathenship. It is not a place for people from other religious "
    "traditions to \"observe\" us or satisfy their curiosity. "
    "Introduce yourself here so we can get to know you a little better "
    "before granting you access to the rest of the rooms.\n\n"
    "Learn more about our tradition at https://ingwine.org/"
)


class WelcomeModule:
    """Greets new users when they join the welcome room."""

    name = "welcome"

    def __init__(self) -> None:
        self._room_name: str | None = None

    async def setup(self, ctx: BotContext) -> None:
        self._room_name = ctx.config.bot.welcome_room
        if not self._room_name:
            log.info("Welcome module disabled (no welcome_room configured)")
            return

        ctx.dispatcher.register_event_handler(
            RoomMemberEvent,
            self.on_member_join,
        )
        log.info("Welcome module active for room: %s", self._room_name)

    async def teardown(self) -> None:
        pass

    async def on_member_join(self, ctx: EventContext) -> None:
        event = ctx.event
        if (
            event.membership == "join"
            and event.prev_membership != "join"
            and ctx.room.display_name == self._room_name
        ):
            user = event.state_key
            log.info("New join in %s: %s", self._room_name, user)
            await ctx.respond(f"{user}: {WELCOME_MSG}")
