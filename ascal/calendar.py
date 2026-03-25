from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import ephem

from ascal.types import AngloSaxonDate, MonthInfo, MoonInfo, TideInfo, YearCalendar

# 13-month (intercalary / three-Liða) year
ALL_MONTH_NAMES = [
    "Æfterra Ġēola",
    "Solmōnaþ",
    "Hreðmōnaþ",
    "Ēosturmōnaþ",
    "Þrimilcemōnaþ",
    "Ærra Liða",
    "Þriliða",
    "Æfterra Liða",
    "Weodmōnaþ",
    "Hāliġmōnaþ",
    "Wintermōnaþ",
    "Blōtmōnaþ",
    "Ærra Ġēola",
]

# 12-month (regular) year — no Þriliða
REGULAR_MONTH_NAMES = [n for n in ALL_MONTH_NAMES if n != "Þriliða"]

# Minimum hours between astronomical new moon and sunset for the crescent
# to be visible to the naked eye (per Ingwine / Bede reconstruction).
CRESCENT_MIN_HOURS = 15.5

OE_WEEKDAYS = [
    "Monandæg",       # Monday
    "Tiwesdæg",       # Tuesday
    "Wodnesdæg",      # Wednesday
    "Þunresdæg",      # Thursday
    "Frigedæg",       # Friday
    "Sæternesdæg",    # Saturday
    "Sunnandæg",      # Sunday
]


class AngloSaxonCalendar:
    """Anglo-Saxon lunisolar calendar using the Ingwine reconstruction.

    Month boundaries are determined by the first visible crescent moon
    (≥ 15.5 hours after the astronomical new moon).  Intercalary (three-Liða)
    years are detected astronomically: if 13 lunar months fit between
    successive winter solstices, Þriliða is inserted.
    """

    def __init__(self, latitude: str, longitude: str, timezone: str):
        self.latitude = latitude
        self.longitude = longitude
        self.tz = ZoneInfo(timezone)

    # ------------------------------------------------------------------
    # Low-level ephem helpers
    # ------------------------------------------------------------------

    def _make_observer(self) -> ephem.Observer:
        obs = ephem.Observer()
        obs.lat = self.latitude
        obs.lon = self.longitude
        return obs

    @staticmethod
    def _ephem_to_datetime(edate: ephem.Date, bod: bool = False) -> datetime:
        c = ephem.Date(edate).tuple()
        if bod:
            return datetime(c[0], c[1], c[2], 0, 0, 0)
        return datetime(c[0], c[1], c[2], c[3], c[4], int(c[5]))

    def _sunset_to_local_date(self, sunset: ephem.Date) -> date:
        """Convert a UTC sunset ephem.Date to a local-timezone Gregorian date."""
        utc_dt = self._ephem_to_datetime(sunset)
        aware = utc_dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(self.tz)
        return aware.date()

    @staticmethod
    def _ephem_to_date(edate: ephem.Date) -> date:
        c = ephem.Date(edate).tuple()
        return date(c[0], c[1], c[2])

    def _get_sunset(self, edate: ephem.Date) -> ephem.Date:
        """Sunset on the calendar day of *edate* (observer location)."""
        obs = self._make_observer()
        obs.date = self._ephem_to_datetime(edate, bod=True)
        return obs.next_setting(ephem.Sun(obs))

    # ------------------------------------------------------------------
    # Crescent-moon logic (Ingwine 15.5-hour rule)
    # ------------------------------------------------------------------

    def _find_crescent_sunset(self, nm: ephem.Date) -> ephem.Date:
        """First sunset ≥ 15.5 h after astronomical new moon *nm*.

        Returns the ephem.Date of that sunset (UTC).  The Anglo-Saxon month
        begins at this sunset.
        """
        day = nm
        for _ in range(5):
            sunset = self._get_sunset(day)
            hours = (sunset - nm) * 24.0
            if hours >= CRESCENT_MIN_HOURS:
                return sunset
            day = day + 1
        raise ValueError(f"No visible crescent found within 5 days of {nm}")

    def _find_all_crescents(
        self, start: ephem.Date, end: ephem.Date
    ) -> list[ephem.Date]:
        """All first-visible-crescent sunsets between *start* and *end*."""
        crescents: list[ephem.Date] = []
        cursor = start
        while True:
            nm = ephem.next_new_moon(cursor)
            sunset = self._find_crescent_sunset(nm)
            if sunset >= end:
                break
            crescents.append(sunset)
            cursor = nm + 15  # skip past this lunation
        return crescents

    # ------------------------------------------------------------------
    # Year calendar (solstice-based intercalary detection)
    # ------------------------------------------------------------------

    @staticmethod
    def _metonic_year(year: int) -> int:
        m = (year - 3) % 19
        return 19 if m == 0 else m

    @lru_cache(maxsize=8)
    def get_year_calendar(self, year: int) -> YearCalendar:
        ws_prev = ephem.next_solstice(datetime(year - 1, 12, 1))
        ws_curr = ephem.next_solstice(datetime(year, 12, 1))
        ss_curr = ephem.next_solstice(datetime(year, 6, 1))

        # Gather crescents from well before ws_prev to well after ws_curr.
        crescents = self._find_all_crescents(ws_prev - 60, ws_curr + 60)

        # Ærra Ġēola of the *previous* AS year = month containing ws_prev.
        ag_prev = None
        for i in range(len(crescents) - 1):
            if crescents[i] <= ws_prev < crescents[i + 1]:
                ag_prev = i
                break
        if ag_prev is None:
            raise ValueError(f"Cannot locate Ærra Ġēola for winter solstice {year - 1}")

        # Æfterra Ġēola = first month of this AS year.
        start = ag_prev + 1

        # Ærra Ġēola of *this* AS year = month containing ws_curr.
        ag_curr = None
        for i in range(start, len(crescents) - 1):
            if crescents[i] <= ws_curr < crescents[i + 1]:
                ag_curr = i
                break
        if ag_curr is None:
            raise ValueError(f"Cannot locate Ærra Ġēola for winter solstice {year}")

        num_months = ag_curr - start + 1  # Æfterra Ġēola … Ærra Ġēola inclusive
        is_intercalary = num_months == 13
        names = list(ALL_MONTH_NAMES) if is_intercalary else list(REGULAR_MONTH_NAMES)

        months: list[MonthInfo] = []
        for j in range(num_months):
            idx = start + j
            begins = self._sunset_to_local_date(crescents[idx])
            fm = self._ephem_to_date(ephem.next_full_moon(crescents[idx]))
            months.append(MonthInfo(name=names[j], begins=begins, full_moon=fm))

        easter = months[4].full_moon
        wf_idx = 10 if is_intercalary else 9
        winterfylleth = months[wf_idx].full_moon

        return YearCalendar(
            year=year,
            metonic_year=self._metonic_year(year),
            is_intercalary=is_intercalary,
            months=months,
            easter=easter,
            midsummer=self._ephem_to_datetime(ss_curr),
            winterfylleth=winterfylleth,
            yule=self._ephem_to_datetime(ws_curr),
        )

    # ------------------------------------------------------------------
    # Sunset helpers for the bot
    # ------------------------------------------------------------------

    def get_sunset_time(self, d: date) -> time:
        """Local sunset time for a given Gregorian date."""
        obs = self._make_observer()
        obs.date = datetime(d.year, d.month, d.day, 0, 0, 0)
        setting = obs.next_setting(ephem.Sun(obs))
        utc_dt = self._ephem_to_datetime(setting)
        aware = utc_dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(self.tz)
        return aware.time()

    def get_sunrise_time(self, d: date) -> time:
        """Local sunrise time for a given Gregorian date."""
        obs = self._make_observer()
        obs.date = datetime(d.year, d.month, d.day, 0, 0, 0)
        rising = obs.next_rising(ephem.Sun(obs))
        utc_dt = self._ephem_to_datetime(rising)
        aware = utc_dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(self.tz)
        return aware.time()

    def get_twilight_times(self, d: date) -> tuple[time, time]:
        """Return (first_light, last_light) civil twilight times for a date.

        Civil twilight: sun center is 6° below the horizon.
        """
        obs = self._make_observer()
        obs.horizon = "-6"
        obs.date = datetime(d.year, d.month, d.day, 0, 0, 0)
        sun = ephem.Sun(obs)
        first = self._ephem_to_datetime(obs.next_rising(sun))
        last = self._ephem_to_datetime(obs.next_setting(sun))
        utc = ZoneInfo("UTC")
        first_local = first.replace(tzinfo=utc).astimezone(self.tz).time()
        last_local = last.replace(tzinfo=utc).astimezone(self.tz).time()
        return first_local, last_local

    @staticmethod
    def _time_to_seconds(t: time) -> float:
        return t.hour * 3600 + t.minute * 60 + t.second

    @staticmethod
    def _seconds_to_time(s: float) -> time:
        s = s % 86400
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        return time(h, m)

    def get_as_day_tides(self, sunset_date: date) -> list[TideInfo]:
        """Return all 8 tides for the AS day starting at sunset on *sunset_date*.

        The AS day runs from sunset on *sunset_date* through the following
        sunrise and daylight to the next sunset.  Order:
        Æfen, Niht, Midniht, Uhta, Morgen, Undern, Middæg, Gelotendæg.
        """
        next_day = sunset_date + timedelta(days=1)
        sunset = self.get_sunset_time(sunset_date)
        sunrise = self.get_sunrise_time(next_day)
        next_sunset = self.get_sunset_time(next_day)

        sunset_s = self._time_to_seconds(sunset)
        sunrise_s = self._time_to_seconds(sunrise)
        next_sunset_s = self._time_to_seconds(next_sunset)

        # Night: sunset_date sunset → next_day sunrise
        # seconds of night, accounting for midnight wrap
        night_s = (86400 - sunset_s) + sunrise_s
        night_q = night_s / 4

        # Daylight: next_day sunrise → next_day sunset
        daylight_s = next_sunset_s - sunrise_s
        day_q = daylight_s / 4

        # Night tides (seconds from sunset_date midnight, may exceed 86400)
        tides = [
            ("Æfen",       sunset_s,                sunset_s + night_q),
            ("Niht",       sunset_s + night_q,      sunset_s + 2 * night_q),
            ("Midniht",    sunset_s + 2 * night_q,  sunset_s + 3 * night_q),
            ("Uhta",       sunset_s + 3 * night_q,  sunset_s + 4 * night_q),
        ]

        # Day tides (seconds from next_day midnight)
        tides += [
            ("Morgen",     sunrise_s,               sunrise_s + day_q),
            ("Undern",     sunrise_s + day_q,       sunrise_s + 2 * day_q),
            ("Middæg",     sunrise_s + 2 * day_q,   sunrise_s + 3 * day_q),
            ("Gelotendæg", sunrise_s + 3 * day_q,   next_sunset_s),
        ]

        return [
            TideInfo(name, self._seconds_to_time(start), self._seconds_to_time(end))
            for name, start, end in tides
        ]

    def get_current_tide(self, now: datetime) -> TideInfo:
        """Determine the current Anglo-Saxon tide based on temporal hours."""
        today = now.date()
        sunset = self.get_sunset_time(today)
        current = now.time()

        if current >= sunset:
            # After sunset: we're in the AS day that started at today's sunset
            tides = self.get_as_day_tides(today)
        else:
            # Before sunset: we're in the AS day that started at yesterday's sunset
            tides = self.get_as_day_tides(today - timedelta(days=1))

        current_s = self._time_to_seconds(current)

        # Night tides (first 4) may wrap past midnight
        for tide in tides[:4]:
            start_s = self._time_to_seconds(tide.starts)
            end_s = self._time_to_seconds(tide.ends)
            if start_s <= end_s:
                if start_s <= current_s < end_s:
                    return tide
            else:
                if current_s >= start_s or current_s < end_s:
                    return tide

        # Day tides (last 4) don't wrap
        for tide in tides[4:]:
            start_s = self._time_to_seconds(tide.starts)
            end_s = self._time_to_seconds(tide.ends)
            if start_s <= current_s < end_s:
                return tide

        # Fallback
        return tides[0]

    # ------------------------------------------------------------------
    # Moon
    # ------------------------------------------------------------------

    def get_moon_info(self, now: datetime | None = None) -> MoonInfo:
        """Return current moon phase, illumination, and upcoming phase dates."""
        if now is None:
            now = datetime.now(self.tz)

        m = ephem.Moon()
        obs = self._make_observer()
        obs.date = ephem.Date(now.astimezone(ZoneInfo("UTC")))
        m.compute(obs)
        illum = m.phase  # 0-100

        # Upcoming phases
        next_new = self._ephem_to_datetime(ephem.next_new_moon(obs.date))
        next_fq = self._ephem_to_datetime(ephem.next_first_quarter_moon(obs.date))
        next_full = self._ephem_to_datetime(ephem.next_full_moon(obs.date))
        next_lq = self._ephem_to_datetime(ephem.next_last_quarter_moon(obs.date))

        # Make aware in user's tz
        utc = ZoneInfo("UTC")
        next_new_local = next_new.replace(tzinfo=utc).astimezone(self.tz)
        next_fq_local = next_fq.replace(tzinfo=utc).astimezone(self.tz)
        next_full_local = next_full.replace(tzinfo=utc).astimezone(self.tz)
        next_lq_local = next_lq.replace(tzinfo=utc).astimezone(self.tz)

        days_to_new = (next_new_local.date() - now.date()).days
        days_to_full = (next_full_local.date() - now.date()).days

        # Determine phase name from illumination and whether waxing or waning
        # Compare: if next full is before next new, we're waxing
        waxing = next_full < next_new
        if illum < 2:
            phase_name = "New Moon"
        elif illum > 98:
            phase_name = "Full Moon"
        elif 48 < illum < 52:
            phase_name = "First Quarter" if waxing else "Last Quarter"
        elif waxing:
            phase_name = "Waxing Crescent" if illum < 50 else "Waxing Gibbous"
        else:
            phase_name = "Waning Gibbous" if illum > 50 else "Waning Crescent"

        return MoonInfo(
            phase_name=phase_name,
            illumination=illum,
            next_new=next_new_local,
            next_first_quarter=next_fq_local,
            next_full=next_full_local,
            next_last_quarter=next_lq_local,
            days_to_new=days_to_new,
            days_to_full=days_to_full,
        )

    # ------------------------------------------------------------------
    # Date conversion
    # ------------------------------------------------------------------

    def get_date(self, d: date) -> AngloSaxonDate:
        """Return the Anglo-Saxon date for an arbitrary Gregorian date.

        Uses solar noon as the time, so the result reflects the daytime
        portion of that Gregorian date (before sunset).
        """
        noon = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=self.tz)
        return self.get_today(now=noon)

    # ------------------------------------------------------------------
    # High-level queries
    # ------------------------------------------------------------------

    def _find_as_month(self, as_date: date) -> tuple[YearCalendar, int]:
        """Find the AS month for a given *as_date* (already sunset-adjusted).

        ``begins`` is the Gregorian date of the sunset that starts the month.
        The first full AS day corresponds to ``begins + 1``, so we compare
        using that effective start.
        """
        one = timedelta(days=1)
        for yr in (as_date.year, as_date.year - 1, as_date.year + 1):
            cal = self.get_year_calendar(yr)
            for i, month in enumerate(cal.months):
                eff_start = month.begins + one
                if i + 1 < len(cal.months):
                    eff_end = cal.months[i + 1].begins + one
                else:
                    next_cal = self.get_year_calendar(yr + 1)
                    eff_end = next_cal.months[0].begins + one
                if eff_start <= as_date < eff_end:
                    return cal, i
        raise ValueError(f"Could not find Anglo-Saxon month for {as_date}")

    def get_today(
        self,
        now: datetime | None = None,
        local_observer: AngloSaxonCalendar | None = None,
    ) -> AngloSaxonDate:
        """Return today's Anglo-Saxon date.

        Month/year boundaries are always computed from *self* (the community
        calendar).  If *local_observer* is given, sunrise/sunset/tides are
        computed for that observer's location instead.
        """
        obs = local_observer or self
        if now is None:
            now = datetime.now(obs.tz)
        today = now.date()
        sunset = obs.get_sunset_time(today)
        sunrise = obs.get_sunrise_time(today)
        first_light, last_light = obs.get_twilight_times(today)
        after_sunset = now.time() >= sunset
        tide = obs.get_current_tide(now)

        # Month lookup always uses self (community calendar)
        as_date = today + timedelta(days=1) if after_sunset else today
        cal, month_idx = self._find_as_month(as_date)
        month = cal.months[month_idx]
        # Day 1 starts on begins+1 (the first full AS day after the sunset).
        day_number = (as_date - month.begins).days

        return AngloSaxonDate(
            month_name=month.name,
            day_number=day_number,
            weekday_oe=self.get_oe_weekday(as_date),
            gregorian=today,
            after_sunset=after_sunset,
            sunset_time=sunset,
            sunrise_time=sunrise,
            first_light=first_light,
            last_light=last_light,
            current_tide=tide,
            year_calendar=cal,
        )

    def get_next_month(self, now: datetime | None = None) -> tuple[str, date]:
        if now is None:
            now = datetime.now(self.tz)
        today = now.date()
        after_sunset = now.time() >= self.get_sunset_time(today)
        as_date = today + timedelta(days=1) if after_sunset else today

        cal, month_idx = self._find_as_month(as_date)
        if month_idx + 1 < len(cal.months):
            nxt = cal.months[month_idx + 1]
            return nxt.name, nxt.begins
        next_cal = self.get_year_calendar(cal.year + 1)
        nxt = next_cal.months[0]
        return nxt.name, nxt.begins

    @staticmethod
    def get_oe_weekday(d: date) -> str:
        return OE_WEEKDAYS[d.weekday()]

    def warm_cache(self, year: int | None = None) -> None:
        if year is None:
            year = datetime.now(self.tz).year
        for y in (year - 1, year, year + 1):
            self.get_year_calendar(y)
