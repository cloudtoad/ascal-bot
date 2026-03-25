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
    current_tide: TideInfo
    year_calendar: YearCalendar
