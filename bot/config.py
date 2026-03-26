"""Typed configuration loaded from TOML."""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field


@dataclass
class MatrixConfig:
    homeserver: str
    username: str
    password: str | None = None
    access_token: str | None = None
    store_path: str = "./crypto_store/"


@dataclass
class CalendarConfig:
    latitude: str
    longitude: str
    timezone: str


@dataclass
class BotConfig:
    prefix: str = "!"
    welcome_room: str | None = None


@dataclass
class ModerationConfig:
    enabled: bool = False
    mod_room_id: str = ""
    new_user_threshold: int = 5


@dataclass
class NotificationConfig:
    admin_users: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    matrix: MatrixConfig
    calendar: CalendarConfig
    bot: BotConfig
    moderation: ModerationConfig
    notifications: NotificationConfig


def load_config(path: str) -> AppConfig:
    """Load configuration from a TOML file with environment variable overrides.

    Supports MATRIX_PASSWORD and MATRIX_ACCESS_TOKEN env var overrides.
    """
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        print(f"Config file not found: {path}", file=sys.stderr)
        print(
            "Copy config.example.toml to config.toml and fill in your details.",
            file=sys.stderr,
        )
        sys.exit(1)

    mc = raw.get("matrix", {})
    cc = raw.get("calendar", {})
    bc = raw.get("bot", {})
    mod = raw.get("moderation", {})
    notif = raw.get("notifications", {})

    # Env var overrides
    if os.environ.get("MATRIX_PASSWORD"):
        mc["password"] = os.environ["MATRIX_PASSWORD"]
    if os.environ.get("MATRIX_ACCESS_TOKEN"):
        mc["access_token"] = os.environ["MATRIX_ACCESS_TOKEN"]

    matrix = MatrixConfig(
        homeserver=mc["homeserver"],
        username=mc["username"],
        password=mc.get("password"),
        access_token=mc.get("access_token"),
        store_path=mc.get("store_path", "./crypto_store/"),
    )

    calendar = CalendarConfig(
        latitude=cc["latitude"],
        longitude=cc["longitude"],
        timezone=cc["timezone"],
    )

    bot = BotConfig(
        prefix=bc.get("prefix", "!"),
        welcome_room=bc.get("welcome_room"),
    )

    moderation = ModerationConfig(
        enabled=mod.get("enabled", False),
        mod_room_id=mod.get("mod_room_id", ""),
        new_user_threshold=int(mod.get("new_user_threshold", 5)),
    )

    notifications = NotificationConfig(
        admin_users=notif.get("admin_users", []),
    )

    return AppConfig(
        matrix=matrix,
        calendar=calendar,
        bot=bot,
        moderation=moderation,
        notifications=notifications,
    )
