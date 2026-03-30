"""Calendar and astronomy module for IngwineBot."""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import unicodedata

from ascal.calendar import AngloSaxonCalendar
from ascal.eclipses import get_upcoming_eclipses
from ascal.holydays import compute_holydays
from bot.context import BotContext, CommandContext
from bot.formatting import (
    format_as_date,
    format_calendar,
    format_eclipses,
    format_holidays,
    format_moon,
    format_next_month,
    format_sun,
    format_tides,
    format_today,
    format_tomorrow,
)
from bot.user_settings import geocode_location, get_user_location, set_user_location

log = logging.getLogger(__name__)


class CalendarModule:
    """Anglo-Saxon calendar, tides, astronomy, and timefacts."""

    name = "calendar"

    def __init__(self) -> None:
        self._default_cal: AngloSaxonCalendar | None = None
        self._default_tz: str = ""
        self._timefacts: list[str] = []
        self._prefix: str = "!"
        self._dispatcher = None

    async def setup(self, ctx: BotContext) -> None:
        cc = ctx.config.calendar
        self._default_tz = cc.timezone
        self._prefix = ctx.config.bot.prefix
        self._dispatcher = ctx.dispatcher

        self._default_cal = AngloSaxonCalendar(
            latitude=cc.latitude,
            longitude=cc.longitude,
            timezone=cc.timezone,
        )
        log.info("Warming calendar cache...")
        self._default_cal.warm_cache()
        log.info("Cache ready.")

        # Load timefacts
        facts_file = Path(__file__).resolve().parent.parent.parent / "data" / "timefacts.txt"
        if facts_file.exists():
            self._timefacts = [f.strip() for f in facts_file.read_text().split("---") if f.strip()]
            log.info("Loaded %d timefacts", len(self._timefacts))
        else:
            log.warning("timefacts.txt not found at %s", facts_file)

        # Register commands
        d = ctx.dispatcher
        d.register_command("today", self.cmd_today, help_text="Today's Anglo-Saxon date")
        d.register_command("tomorrow", self.cmd_tomorrow, aliases=["morgen"], help_text="Tomorrow's AS date and sun times")
        d.register_command("nextmonth", self.cmd_nextmonth, help_text="When the next AS month begins")
        d.register_command("calendar", self.cmd_calendar, help_text="Full month table for the current AS year")
        d.register_command("tides", self.cmd_tides, help_text="All 8 tides for the current AS day")
        d.register_command("nexttides", self.cmd_nexttides, help_text="All 8 tides starting from the upcoming sunset")
        d.register_command("sun", self.cmd_sun, help_text="Current sun position, shadow direction and length")
        d.register_command("moon", self.cmd_moon, help_text="Current moon phase and upcoming phases")
        d.register_command("eclipses", self.cmd_eclipses, help_text="Upcoming lunar and solar eclipses")
        d.register_command("date", self.cmd_date, help_text="Convert a Gregorian date to AS (YYYY-MM-DD)")
        d.register_command("asdate", self.cmd_asdate, help_text="Convert an AS date to Gregorian (MonthName Day [Year])")
        d.register_command("holidays", self.cmd_holidays, help_text="Ingwine holy calendar for the current year")
        d.register_command("location", self.cmd_location, help_text="Set your location (City, State/Country)")
        d.register_command("timefact", self.cmd_timefact, help_text="Random fact about Germanic/Celtic ethnoastronomy")
        d.register_command("help", self.cmd_help, help_text="This help message")

    async def teardown(self) -> None:
        pass

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_local_observer(self, user_id: str) -> tuple[AngloSaxonCalendar | None, str, str]:
        """Return (observer_or_None, timezone, tide_lang) for a user."""
        loc = get_user_location(user_id)
        if loc is None:
            return None, self._default_tz, "oe"
        return AngloSaxonCalendar(
            latitude=loc["latitude"],
            longitude=loc["longitude"],
            timezone=loc["timezone"],
        ), loc["timezone"], loc.get("tide_lang", "oe")

    # ── Commands ──────────────────────────────────────────────────────────

    async def cmd_today(self, ctx: CommandContext) -> None:
        obs, tz, tide_lang = self._get_local_observer(ctx.sender)
        asd = self._default_cal.get_today(local_observer=obs)
        await ctx.respond(format_today(asd, tz, tide_lang))

    async def cmd_tomorrow(self, ctx: CommandContext) -> None:
        obs, tz, _tide_lang = self._get_local_observer(ctx.sender)
        tomorrow = datetime.now(ZoneInfo(tz)).date() + timedelta(days=1)
        asd = self._default_cal.get_date(tomorrow)
        if obs:
            asd.sunrise_time = obs.get_sunrise_time(tomorrow)
            asd.sunset_time = obs.get_sunset_time(tomorrow)
            asd.first_light, asd.last_light = obs.get_twilight_times(tomorrow)
        await ctx.respond(format_tomorrow(asd))

    async def cmd_nextmonth(self, ctx: CommandContext) -> None:
        name, begins = self._default_cal.get_next_month()
        await ctx.respond(format_next_month(name, begins))

    async def cmd_calendar(self, ctx: CommandContext) -> None:
        asd = self._default_cal.get_today()
        await ctx.respond(format_calendar(asd.year_calendar))

    async def cmd_tides(self, ctx: CommandContext) -> None:
        obs, tz, tide_lang = self._get_local_observer(ctx.sender)
        cal = obs or self._default_cal
        now = datetime.now(ZoneInfo(tz))
        sunset = cal.get_sunset_time(now.date())
        if now.time() >= sunset:
            sunset_date = now.date()
        else:
            sunset_date = now.date() - timedelta(days=1)
        tides = cal.get_as_day_tides(sunset_date)
        current = cal.get_current_tide(now)
        await ctx.respond(format_tides(tides, current, f"Tides for the current AS day ({tz})", tide_lang))

    async def cmd_nexttides(self, ctx: CommandContext) -> None:
        obs, tz, tide_lang = self._get_local_observer(ctx.sender)
        cal = obs or self._default_cal
        now = datetime.now(ZoneInfo(tz))
        sunset = cal.get_sunset_time(now.date())
        if now.time() >= sunset:
            sunset_date = now.date() + timedelta(days=1)
        else:
            sunset_date = now.date()
        tides = cal.get_as_day_tides(sunset_date)
        current = cal.get_current_tide(now)
        await ctx.respond(format_tides(tides, current, f"Tides starting next sunset ({tz})", tide_lang))

    async def cmd_sun(self, ctx: CommandContext) -> None:
        obs, tz, _tide_lang = self._get_local_observer(ctx.sender)
        cal = obs or self._default_cal
        sun = cal.get_sun_info()
        await ctx.respond(format_sun(sun))

    async def cmd_moon(self, ctx: CommandContext) -> None:
        obs, tz, _tide_lang = self._get_local_observer(ctx.sender)
        cal = obs or self._default_cal
        moon = cal.get_moon_info()
        await ctx.respond(format_moon(moon))

    async def cmd_eclipses(self, ctx: CommandContext) -> None:
        obs, tz, _tide_lang = self._get_local_observer(ctx.sender)
        cal = obs or self._default_cal
        eclipses = get_upcoming_eclipses(
            ZoneInfo(tz),
            float(cal.latitude),
            float(cal.longitude),
        )
        await ctx.respond(format_eclipses(eclipses))

    async def cmd_date(self, ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.respond(f"Usage: `{self._prefix}date YYYY-MM-DD`")
            return
        try:
            d = date.fromisoformat(ctx.args[0])
        except ValueError:
            await ctx.respond(f"Invalid date format. Use `{self._prefix}date YYYY-MM-DD`.")
            return
        asd = self._default_cal.get_date(d)
        await ctx.respond(format_as_date(asd))

    @staticmethod
    def _normalize_month(name: str) -> str:
        """Strip diacritics and lowercase for fuzzy month matching."""
        # Decompose unicode, drop combining marks, lowercase
        nfkd = unicodedata.normalize("NFKD", name)
        stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
        # Replace ð/þ with their ASCII equivalents
        stripped = stripped.replace("ð", "th").replace("Ð", "th")
        stripped = stripped.replace("þ", "th").replace("Þ", "th")
        stripped = stripped.replace("æ", "ae").replace("Æ", "ae")
        return stripped.lower().strip()

    def _find_month_by_name(self, cal_months, name: str):
        """Find a month by fuzzy name match."""
        target = self._normalize_month(name)
        for m in cal_months:
            if self._normalize_month(m.name) == target:
                return m
            # Also try without -monath suffix
            if target in self._normalize_month(m.name):
                return m
        return None

    async def cmd_asdate(self, ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.respond(
                f"Usage: `{self._prefix}asdate MonthName Day [Year]`\n"
                f"Example: `{self._prefix}asdate Hrethmonath 4` or "
                f"`{self._prefix}asdate Hrethmonath 4 2027`"
            )
            return

        month_name = ctx.args[0]
        try:
            day_num = int(ctx.args[1])
        except ValueError:
            await ctx.respond("Day must be a number.")
            return

        year = int(ctx.args[2]) if len(ctx.args) > 2 else datetime.now(ZoneInfo(self._default_tz)).year
        cal = self._default_cal.get_year_calendar(year)
        month = self._find_month_by_name(cal.months, month_name)

        if month is None:
            names = ", ".join(m.name for m in cal.months)
            await ctx.respond(f"Could not find month \"{month_name}\". Available: {names}")
            return

        greg_date = month.begins + timedelta(days=day_num)
        asd = self._default_cal.get_date(greg_date)
        await ctx.respond(
            f"Day {day_num} of {month.name} ({year}) = "
            f"**{greg_date.strftime('%A, %d %B %Y')}**\n"
            f"{asd.weekday_oe}"
        )

    async def cmd_holidays(self, ctx: CommandContext) -> None:
        asd = self._default_cal.get_today()
        holydays = compute_holydays(asd.year_calendar)
        await ctx.respond(format_holidays(holydays, asd.year_calendar.year))

    async def cmd_location(self, ctx: CommandContext) -> None:
        place = " ".join(ctx.args)
        if not place:
            loc = get_user_location(ctx.sender)
            if loc:
                await ctx.respond(
                    f"Your location: {loc.get('display_name', 'unknown')} ({loc['timezone']})"
                )
            else:
                await ctx.respond(
                    f"No location set. Use `{self._prefix}location City, State/Country` to set one."
                )
            return
        result = geocode_location(place)
        if result is None:
            await ctx.respond(f"Could not find a location matching \"{place}\".")
            return
        display_name, lat, lon, tz, tide_lang = result
        set_user_location(ctx.sender, lat, lon, tz, display_name, tide_lang)
        from bot.tide_names import LANG_DISPLAY_NAMES
        lang_name = LANG_DISPLAY_NAMES.get(tide_lang, tide_lang)
        await ctx.respond(f"Location set to **{display_name}** ({tz})\nTide names: {lang_name}")

    async def cmd_timefact(self, ctx: CommandContext) -> None:
        if self._timefacts:
            await ctx.respond(random.choice(self._timefacts))
        else:
            await ctx.respond("No timefacts available.")

    async def cmd_help(self, ctx: CommandContext) -> None:
        lines = ["**IngwineBot**", ""]
        for entry in sorted(self._dispatcher.get_commands(), key=lambda e: e.name):
            if not entry.help_text:
                continue
            alias_str = ""
            if entry.aliases:
                alias_names = ", ".join(f"`{self._prefix}{a}`" for a in entry.aliases)
                alias_str = f" (also {alias_names})"
            lines.append(f"`{self._prefix}{entry.name}` — {entry.help_text}{alias_str}")
        await ctx.respond("\n".join(lines))
