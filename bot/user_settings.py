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


def set_user_location(
    user_id: str, latitude: str, longitude: str, timezone: str,
    display_name: str = "", tide_lang: str = "oe",
) -> None:
    data = _load()
    data[user_id] = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "display_name": display_name,
        "tide_lang": tide_lang,
    }
    _save(data)


def set_user_tide_lang(user_id: str, tide_lang: str) -> bool:
    """Override the tide name language for a user. Returns True if the user exists."""
    data = _load()
    if user_id not in data:
        return False
    data[user_id]["tide_lang"] = tide_lang
    _save(data)
    return True


def geocode_location(place: str) -> tuple[str, str, str, str, str] | None:
    """Resolve a place name to (display_name, latitude, longitude, timezone, tide_lang).

    Returns None if the place cannot be found.
    tide_lang is one of: "oe" (Old English), "md" (Middle Dutch), or others
    as we add them.
    """
    loc = _geocoder.geocode(place, addressdetails=True)
    if loc is None:
        return None
    tz = _tzfinder.timezone_at(lat=loc.latitude, lng=loc.longitude)
    if tz is None:
        return None
    tide_lang = _detect_tide_language(loc.raw.get("address", {}))
    return loc.address, str(loc.latitude), str(loc.longitude), tz, tide_lang


# ── Tide language detection ──────────────────────────────────────────

# Belgian provinces/states that are Dutch-speaking (Flanders + Brussels)
_FLEMISH_STATES = {
    "antwerpen", "oost-vlaanderen", "west-vlaanderen",
    "vlaams-brabant", "limburg",
}

# Country code → tide language.
# "oe" = Old English, "md" = Middle Dutch
_COUNTRY_TIDE_LANG = {
    # English-speaking → Old English
    "gb": "oe", "ie": "oe", "us": "oe", "ca": "oe",
    "au": "oe", "nz": "oe",
    # Dutch-speaking → Middle Dutch
    "nl": "md", "sr": "md",
    # Belgium is handled specially below
    # Everything else defaults to OE for now
}


def _detect_tide_language(address: dict) -> str:
    """Detect the appropriate tide name language from a Nominatim address.

    Returns a language code: "oe" (Old English), "md" (Middle Dutch), etc.
    """
    cc = address.get("country_code", "").lower()

    # Belgium: depends on region
    if cc == "be":
        state = (address.get("state") or "").lower()
        city = (address.get("city") or address.get("town") or "").lower()
        # Brussels is bilingual but Dutch is one of the two
        if "brussel" in city or "bruxelles" in city:
            return "md"
        if state in _FLEMISH_STATES:
            return "md"
        # Wallonia → default to OE (French speakers, no Germanic reconstruction)
        return "oe"

    return _COUNTRY_TIDE_LANG.get(cc, "oe")
