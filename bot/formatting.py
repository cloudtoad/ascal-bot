from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ascal.eclipses import EclipseInfo
from ascal.types import AngloSaxonDate, MoonInfo, SunInfo, TideInfo, YearCalendar


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
        f"First light: {asd.first_light.strftime('%H:%M')}",
        f"Sunrise: {asd.sunrise_time.strftime('%H:%M')}",
        f"Sunset: {asd.sunset_time.strftime('%H:%M')}",
        f"Last light: {asd.last_light.strftime('%H:%M')}",
    ]

    if asd.after_sunset:
        lines.append("")
        lines.append(
            f"*It is now night \u2014 the Anglo-Saxon day has turned to {asd.weekday_oe}.*"
        )

    return "\n".join(lines)


def format_tomorrow(asd: AngloSaxonDate) -> str:
    lines = [
        f"**Morgen: {asd.weekday_oe}, day {asd.day_number} of {asd.month_name}**",
        "",
        f"Modern date: {asd.gregorian.strftime('%A, %d %B %Y')}",
        f"First light: {asd.first_light.strftime('%H:%M')}",
        f"Sunrise: {asd.sunrise_time.strftime('%H:%M')}",
        f"Sunset: {asd.sunset_time.strftime('%H:%M')}",
        f"Last light: {asd.last_light.strftime('%H:%M')}",
    ]
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


def format_moon(moon: MoonInfo) -> str:
    lines = [
        f"**{moon.phase_name}** ({moon.illumination:.1f}% illuminated)",
        "",
        f"Next New Moon: {moon.next_new.strftime('%a %d %b %H:%M')} ({moon.days_to_new}d)",
        f"Next First Quarter: {moon.next_first_quarter.strftime('%a %d %b %H:%M')}",
        f"Next Full Moon: {moon.next_full.strftime('%a %d %b %H:%M')} ({moon.days_to_full}d)",
        f"Next Last Quarter: {moon.next_last_quarter.strftime('%a %d %b %H:%M')}",
    ]
    return "\n".join(lines)


def format_as_date(asd: AngloSaxonDate) -> str:
    """Format an AS date for the !date conversion command."""
    lines = [
        f"**{asd.gregorian.strftime('%A, %d %B %Y')}**",
        "",
        f"{asd.weekday_oe}, day {asd.day_number} of {asd.month_name}",
        f"First light: {asd.first_light.strftime('%H:%M')}",
        f"Sunrise: {asd.sunrise_time.strftime('%H:%M')}",
        f"Sunset: {asd.sunset_time.strftime('%H:%M')}",
        f"Last light: {asd.last_light.strftime('%H:%M')}",
    ]
    return "\n".join(lines)


def format_sun(sun: SunInfo) -> str:
    if sun.altitude <= 0:
        return (
            f"**The sun is below the horizon**\n\n"
            f"Altitude: {sun.altitude}\u00b0\n"
            f"Azimuth: {sun.azimuth}\u00b0"
        )
    lines = [
        f"**Sun Position**",
        "",
        f"Altitude: {sun.altitude}\u00b0 above horizon",
        f"Azimuth: {sun.azimuth}\u00b0 ({_az_to_compass(sun.azimuth)})",
        f"Shadow points: {sun.shadow_dir}",
        f"Shadow length: {sun.shadow_ratio}\u00d7 object height",
    ]
    return "\n".join(lines)


def _az_to_compass(az: float) -> str:
    points = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    return points[int((az + 11.25) % 360 / 22.5)]


def format_eclipses(eclipses: list[EclipseInfo]) -> str:
    if not eclipses:
        return "No upcoming eclipses found."
    lines = ["**Upcoming Eclipses**", ""]
    for e in eclipses:
        blood = " (Blood Moon)" if e.type == "lunar" and e.kind == "Total" else ""
        lines.append(
            f"{e.peak_local.strftime('%a %d %b %Y %H:%M')} — {e.description}{blood}"
        )
    return "\n".join(lines)


def format_help(prefix: str) -> str:
    return (
        f"**Anglo-Saxon Calendar Bot**\n\n"
        f"`{prefix}today` — Today's Anglo-Saxon date\n"
        f"`{prefix}tomorrow` — Tomorrow's AS date and sun times (also `{prefix}morgen`)\n"
        f"`{prefix}nextmonth` — When the next AS month begins\n"
        f"`{prefix}calendar` — Full month table for the current AS year\n"
        f"`{prefix}tides` — All 8 tides for the current AS day\n"
        f"`{prefix}nexttides` — All 8 tides starting from the upcoming sunset\n"
        f"`{prefix}moon` — Current moon phase and upcoming phases\n"
        f"`{prefix}date YYYY-MM-DD` — Convert a Gregorian date to AS\n"
        f"`{prefix}sun` — Current sun position, shadow direction and length\n"
        f"`{prefix}eclipses` — Upcoming lunar and solar eclipses\n"
        f"`{prefix}timefact` — Random fact about Germanic/Celtic ethnoastronomy\n"
        f"`{prefix}holidays` — The four major holidays\n"
        f"`{prefix}location City, State` — Set your location for local sunrise/sunset/tides\n"
        f"`{prefix}location` — Show your current location\n"
        f"`{prefix}help` — This help message"
    )
