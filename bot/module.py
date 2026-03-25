"""Module protocol for IngwineBot extensions."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bot.context import BotContext


@runtime_checkable
class Module(Protocol):
    """Interface that every bot module must implement."""

    name: str

    async def setup(self, ctx: BotContext) -> None:
        """Called once during bot startup to register commands and handlers."""
        ...

    async def teardown(self) -> None:
        """Called during bot shutdown for cleanup."""
        ...
