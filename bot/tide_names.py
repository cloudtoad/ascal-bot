"""Tide name translations for regional display.

The AS calendar engine always uses Old English tide names internally.
This module translates them to the appropriate regional historical
Germanic language for display, based on the user's location.

Currently supported:
  oe = Old English (default)
  md = Middle Dutch (for Netherlands, Flanders, Brussels)
"""
from __future__ import annotations

# OE name → { lang_code: translated name }
# OE names are canonical (used by the calendar engine).
TIDE_NAMES: dict[str, dict[str, str]] = {
    "Æfen": {
        "oe": "Æfen",
        "md": "Âvont",
    },
    "Niht": {
        "oe": "Niht",
        "md": "Nacht",
    },
    "Midniht": {
        "oe": "Midniht",
        "md": "Middernacht",
    },
    "Uhta": {
        "oe": "Uhta",
        "md": "Ochte",
    },
    "Morgen": {
        "oe": "Morgen",
        "md": "Morghen",
    },
    "Undern": {
        "oe": "Undern",
        "md": "Onderen",
    },
    "Middæg": {
        "oe": "Middæg",
        "md": "Middach",
    },
    "Ofer Midne Dæg": {
        "oe": "Ofer Midne Dæg",
        "md": "Nâmiddach",
    },
}

LANG_DISPLAY_NAMES = {
    "oe": "Old English",
    "md": "Middle Dutch",
}


def translate_tide(oe_name: str, lang: str = "oe") -> str:
    """Translate an OE tide name to the target language.

    Falls back to the OE name if the language or tide is unknown.
    """
    return TIDE_NAMES.get(oe_name, {}).get(lang, oe_name)
