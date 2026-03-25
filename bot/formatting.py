from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ascal.types import AngloSaxonDate, TideInfo, YearCalendar


def format_today(asd: AngloSaxonDate, timezone: str) -> str:
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    tide = asd.current_tide
    lines = [
        f"**{asd.weekday_oe}, day {asd.day_number} of {asd.month_name}**",
        "",
        f"Modern date: {asd.gregorian.strftime('%A, %d %B %Y')}",
        f"Local time: {now.strftime('%H:%M')} ({timezone})",
        f"Current tide: **{tide.name}** ({tide.starts.strftime('%H:%M')}\u2013{tide.ends.strftime('%H:%M')})",
        f"Sunrise: {asd.sunrise_time.strftime('%H:%M')} / Sunset: {asd.sunset_time.strftime('%H:%M')}",
    ]

    if asd.after_sunset:
        lines.append("")
        lines.append(
            f"*It is now night \u2014 the Anglo-Saxon day has turned to {asd.weekday_oe}.*"
        )

    return "\n".join(lines)


def format_next_month(name: str, begins: date) -> str:
    delta = (begins - date.today()).days
    return (
        f"The next Anglo-Saxon month is **{name}**, "
        f"beginning on {begins.strftime('%A, %d %B %Y')} ({delta} days from now)."
    )


def format_calendar(cal: YearCalendar) -> str:
    leap = "Leap year" if cal.is_intercalary else "Regular year"
    lines = [
        f"**Reconstructed Anglo-Saxon Calendar for {cal.year}**",
        f"Metonic Year {cal.metonic_year}: {leap}",
        "",
    ]
    for m in cal.months:
        lines.append(f"{m.name}: {m.begins} (full moon {m.full_moon})")
    return "\n".join(lines)


def format_holidays(cal: YearCalendar) -> str:
    lines = [
        f"**Holidays for {cal.year}**",
        "",
        f"Eosturd\u00e6g: {cal.easter}",
        f"Midsumor: {cal.midsummer.strftime('%Y-%m-%d %H:%M')}",
        f"Winterfylle\u00fe: {cal.winterfylleth}",
        f"Yule: {cal.yule.strftime('%Y-%m-%d %H:%M')}",
    ]
    return "\n".join(lines)


def _tide_duration(tide: TideInfo) -> str:
    start_m = tide.starts.hour * 60 + tide.starts.minute
    end_m = tide.ends.hour * 60 + tide.ends.minute
    diff = (end_m - start_m) % 1440
    return f"{diff // 60}:{diff % 60:02d}"


def format_tides(tides: list[TideInfo], current_tide: TideInfo, label: str) -> str:
    lines = [f"**{label}**", ""]
    for tide in tides:
        marker = " **\u25c0**" if tide.name == current_tide.name else ""
        dur = _tide_duration(tide)
        lines.append(
            f"{tide.name}: {tide.starts.strftime('%H:%M')}\u2013{tide.ends.strftime('%H:%M')} ({dur}){marker}"
        )
    return "\n".join(lines)


def format_help(prefix: str) -> str:
    return (
        f"**Anglo-Saxon Calendar Bot**\n\n"
        f"`{prefix}today` — Today's Anglo-Saxon date\n"
        f"`{prefix}nextmonth` — When the next AS month begins\n"
        f"`{prefix}calendar` — Full month table for the current AS year\n"
        f"`{prefix}tides` — All 8 tides for the current AS day\n"
        f"`{prefix}nexttides` — All 8 tides starting from the upcoming sunset\n"
        f"`{prefix}holidays` — The four major holidays\n"
        f"`{prefix}location City, State` — Set your location for local sunrise/sunset/tides\n"
        f"`{prefix}location` — Show your current location\n"
        f"`{prefix}help` — This help message"
    )
