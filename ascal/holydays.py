"""Ingwine holy day computation from the Anglo-Saxon lunisolar calendar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ascal.types import YearCalendar


@dataclass
class HolyDay:
    name_oe: str
    name_en: str
    date: date
    gods: str
    description: str


def _find_month(cal: YearCalendar, name: str):
    """Find a month by name in the calendar. Returns MonthInfo or None."""
    for m in cal.months:
        if m.name == name:
            return m
    return None


def compute_holydays(cal: YearCalendar) -> list[HolyDay]:
    """Compute all Ingwine holy days for a given AS year calendar.

    Returns holy days sorted by date.
    """
    days: list[HolyDay] = []
    solstice = cal.yule.date() if hasattr(cal.yule, 'date') else cal.yule

    # ── Yuletide ─────────────────────────────────────────────────────────

    days.append(HolyDay(
        name_oe="Géohol-blót",
        name_en="Yule Night",
        date=solstice,
        gods="Wōden, Wulþ, Þunor, Ingui-Fréa, Frig",
        description="The Winter Solstice — longest night, return of the sun",
    ))

    days.append(HolyDay(
        name_oe="Módraniht",
        name_en="Mothers' Night",
        date=solstice + timedelta(days=5),
        gods="Idese, Mettena",
        description="Sixth night of Yule — honoring the ancestral mothers",
    ))

    days.append(HolyDay(
        name_oe="Twelftadæg",
        name_en="Twelfth Day",
        date=solstice + timedelta(days=11),
        gods="Frig, nature spirits",
        description="Final night of Yule — wassailing, first footing",
    ))

    # ── Early Spring ─────────────────────────────────────────────────────

    sol = _find_month(cal, "Solmōnaþ")
    if sol:
        days.append(HolyDay(
            name_oe="Āwæcnungdæg",
            name_en="Awakening Day",
            date=sol.full_moon,
            gods="Ingui-Fréa, Gerd",
            description="Full Moon in Solmōnaþ — Gerd's awakening, love and renewal",
        ))

        days.append(HolyDay(
            name_oe="Sige-tiber",
            name_en="Victory Sacrifice",
            date=sol.full_moon + timedelta(days=9),
            gods="Wōden",
            description="Nine days after Awakening Day — bonfires, victory over winter",
        ))

    # ── Spring and Early Summer ──────────────────────────────────────────

    hreth = _find_month(cal, "Hreðmōnaþ")
    if hreth:
        days.append(HolyDay(
            name_oe="Lencten-tíd",
            name_en="Springtide",
            date=hreth.full_moon,
            gods="Hréðe, Hludana",
            description="Full Moon in Hreðmōnaþ — feast of the spring goddesses",
        ))

    eostur = _find_month(cal, "Ēosturmōnaþ")
    if eostur:
        days.append(HolyDay(
            name_oe="Éaster-freólsdæg",
            name_en="Éostre's Feast",
            date=eostur.full_moon,
            gods="Éostre",
            description="Full Moon in Ēosturmōnaþ — spring fertility, eggs, the hare",
        ))

    thri = _find_month(cal, "Þrimilcemōnaþ")
    if thri:
        # Blostm-freóls: the new moon / beginning of Þrimilcemōnaþ
        days.append(HolyDay(
            name_oe="Blostm-freóls",
            name_en="Blossom Festival",
            date=thri.begins + timedelta(days=1),
            gods="Þunor, Geofon, Fosite",
            description="New Moon in Þrimilcemōnaþ — Mayday, folk-moot, blossom and growth",
        ))

    # ── Midsummer ────────────────────────────────────────────────────────

    midsummer = cal.midsummer.date() if hasattr(cal.midsummer, 'date') else cal.midsummer
    days.append(HolyDay(
        name_oe="Midsumordæg",
        name_en="Midsummer Day",
        date=midsummer,
        gods="Helið, Ingui-Fréa, Sunne",
        description="Summer Solstice — longest day, bonfires, bathing, mugwort",
    ))

    # ── Harvest Season ───────────────────────────────────────────────────

    weod = _find_month(cal, "Weodmōnaþ")
    if weod:
        days.append(HolyDay(
            name_oe="Bendfeorm",
            name_en="Binding Feast",
            date=weod.begins + timedelta(days=1),
            gods="Beowa, Ing",
            description="First day of Weodmōnaþ — first grain harvest, loaf feast",
        ))

    halig = _find_month(cal, "Hāliġmōnaþ")
    if halig:
        days.append(HolyDay(
            name_oe="Hærfestlíc Freólsung",
            name_en="Autumn Festival",
            date=halig.full_moon + timedelta(days=1),
            gods="Wōden, Frig",
            description="After the Full Moon in Hāliġmōnaþ — last sheaf, Wōden's horse",
        ))

    # Winterfylleþ: the full moon that starts winter
    # Find the month that corresponds to Wintermōnaþ (October equivalent)
    winter = _find_month(cal, "Wintermōnaþ")
    if winter:
        days.append(HolyDay(
            name_oe="Winter-fylleþ",
            name_en="Winter Full Moon",
            date=winter.full_moon,
            gods="Wōden, Ingui, Ælfe",
            description="Full Moon in Wintermōnaþ — start of winter, the Wild Hunt, honoring the Ælfe",
        ))

    blot = _find_month(cal, "Blōtmōnaþ")
    if blot:
        days.append(HolyDay(
            name_oe="Andetnes-blót",
            name_en="Thanksgiving Sacrifice",
            date=blot.full_moon + timedelta(days=7),
            gods="Seaxnéat, Tanfana, Nehalennia",
            description="Week after the Full Moon in Blōtmōnaþ — month of immolations, giving thanks",
        ))

    days.sort(key=lambda d: d.date)
    return days
