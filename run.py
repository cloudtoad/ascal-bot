"""IngwineBot entry point."""
import asyncio
import os
import signal
import sys

from bot.config import load_config
from bot.core import BotCore
from bot.logging_setup import setup_logging
from bot.modules.calendar_mod import CalendarModule
from bot.modules.moderation_mod import ModerationModule
from bot.modules.welcome_mod import WelcomeModule

config = load_config(os.environ.get("CONFIG_PATH", "config.toml"))
setup_logging(config)

bot = BotCore(config)
bot.register_module(CalendarModule())
bot.register_module(ModerationModule())
bot.register_module(WelcomeModule())


def _handle_signal(sig: int, frame: object) -> None:
    """Graceful shutdown on SIGINT/SIGTERM."""
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, _handle_signal)

try:
    asyncio.run(bot.start())
except KeyboardInterrupt:
    asyncio.run(bot.stop())
