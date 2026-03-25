from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass
class MonthInfo:
    name: str
    begins: date
    full_moon: date


@dataclass
class YearCalendar:
    year: int
    metonic_year: int
    is_intercalary: bool
    months: list[MonthInfo]
    easter: date
    midsummer: datetime
    winterfylleth: date
    yule: datetime


@dataclass
class MoonInfo:
    phase_name: str
    illumination: float
    next_new: datetime
    next_first_quarter: datetime
    next_full: datetime
    next_last_quarter: datetime
    days_to_new: int
    days_to_full: int


@dataclass
class SunInfo:
    altitude: float  # degrees above horizon
    azimuth: float  # degrees from north
    shadow_dir: str  # compass direction the shadow points
    shadow_ratio: float | None  # shadow length / object height (None if sun below horizon)


@dataclass
class TideInfo:
    name: str
    starts: time
    ends: time


@dataclass
class AngloSaxonDate:
    month_name: str
    day_number: int
    weekday_oe: str
    gregorian: date
    after_sunset: bool
    sunset_time: time
    sunrise_time: time
    first_light: time
    last_light: time
    current_tide: TideInfo
    year_calendar: YearCalendar
