"""Logging configuration for IngwineBot."""
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.config import AppConfig


def setup_logging(config: AppConfig) -> None:
    """Configure the root logger and module-level loggers.

    - Root logger: INFO to stderr.
    - Module loggers live under ``bot.modules.*``.
    - nio is noisy at INFO; set it to WARNING.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Clear any existing handlers (e.g. from basicConfig)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet down noisy libraries
    logging.getLogger("nio").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)
