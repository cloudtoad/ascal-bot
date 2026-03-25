from __future__ import annotations

import json
import logging
from pathlib import Path

from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

log = logging.getLogger(__name__)

SETTINGS_FILE = Path("user_settings.json")

_geocoder = Nominatim(user_agent="ascal-bot")
_tzfinder = TimezoneFinder()


def _load() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {}


def _save(data: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def get_user_location(user_id: str) -> dict | None:
    """Return {"latitude": str, "longitude": str, "timezone": str} or None."""
    data = _load()
    return data.get(user_id)


def set_user_location(user_id: str, latitude: str, longitude: str, timezone: str, display_name: str = "") -> None:
    data = _load()
    data[user_id] = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "display_name": display_name,
    }
    _save(data)


def geocode_location(place: str) -> tuple[str, str, str, str] | None:
    """Resolve a place name to (display_name, latitude, longitude, timezone).

    Returns None if the place cannot be found.
    """
    loc = _geocoder.geocode(place)
    if loc is None:
        return None
    tz = _tzfinder.timezone_at(lat=loc.latitude, lng=loc.longitude)
    if tz is None:
        return None
    return loc.address, str(loc.latitude), str(loc.longitude), tz
