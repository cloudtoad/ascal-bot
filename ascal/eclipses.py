from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import astronomy


@dataclass
class EclipseInfo:
    type: str  # "lunar" or "solar"
    kind: str  # "Total", "Partial", "Penumbral", "Annular"
    peak_utc: datetime
    peak_local: datetime
    obscuration: float | None

    @property
    def description(self) -> str:
        return f"{self.kind} {self.type} eclipse"


_KIND_NAMES = {
    astronomy.EclipseKind.Penumbral: "Penumbral",
    astronomy.EclipseKind.Partial: "Partial",
    astronomy.EclipseKind.Total: "Total",
    astronomy.EclipseKind.Annular: "Annular",
}


def _astro_time_to_utc(at: astronomy.Time) -> datetime:
    utc = at.Utc()
    return datetime(
        utc.year, utc.month, utc.day,
        utc.hour, utc.minute, int(utc.second),
        tzinfo=timezone.utc,
    )


def _is_lunar_eclipse_visible(peak_utc: datetime, lat: float, lon: float) -> bool:
    """Check if the moon is above the horizon at eclipse peak for the observer."""
    obs = astronomy.Observer(lat, lon, 0)
    t = astronomy.Time.Make(
        peak_utc.year, peak_utc.month, peak_utc.day,
        peak_utc.hour, peak_utc.minute, peak_utc.second,
    )
    moon_eq = astronomy.Equator(astronomy.Body.Moon, t, obs, True, True)
    moon_hor = astronomy.Horizon(t, obs, moon_eq.ra, moon_eq.dec, astronomy.Refraction.Normal)
    return moon_hor.altitude > 0


def get_upcoming_eclipses(
    tz: ZoneInfo,
    lat: float,
    lon: float,
    count: int = 10,
    from_date: datetime | None = None,
) -> list[EclipseInfo]:
    """Return the next *count* eclipses visible from the observer's location."""
    if from_date is None:
        from_date = datetime.now(timezone.utc)
    start = astronomy.Time.Make(
        from_date.year, from_date.month, from_date.day,
        from_date.hour, from_date.minute, from_date.second,
    )
    end = astronomy.Time.Make(from_date.year + 5, 1, 1, 0, 0, 0)
    results: list[EclipseInfo] = []
    obs = astronomy.Observer(lat, lon, 0)

    # Lunar eclipses — visible if the moon is above the horizon at peak
    t = start
    while t.ut < end.ut and len(results) < count * 3:
        e = astronomy.SearchLunarEclipse(t)
        if e.peak.ut >= end.ut:
            break
        peak_utc = _astro_time_to_utc(e.peak)
        if peak_utc >= from_date.astimezone(timezone.utc):
            if _is_lunar_eclipse_visible(peak_utc, lat, lon):
                results.append(EclipseInfo(
                    type="lunar",
                    kind=_KIND_NAMES.get(e.kind, str(e.kind)),
                    peak_utc=peak_utc,
                    peak_local=peak_utc.astimezone(tz),
                    obscuration=e.obscuration if e.obscuration and not math.isnan(e.obscuration) else None,
                ))
        t = astronomy.Time(e.peak.ut + 20)

    # Solar eclipses — use local search for observer's location
    t = start
    while t.ut < end.ut and len(results) < count * 3:
        e = astronomy.SearchLocalSolarEclipse(t, obs)
        if e.peak.time.ut >= end.ut:
            break
        peak_utc = _astro_time_to_utc(e.peak.time)
        if peak_utc >= from_date.astimezone(timezone.utc):
            kind = _KIND_NAMES.get(e.kind, str(e.kind))
            # SearchLocalSolarEclipse returns "none" kind if not visible
            if e.kind != astronomy.EclipseKind.Penumbral and kind != "None":
                results.append(EclipseInfo(
                    type="solar",
                    kind=kind,
                    peak_utc=peak_utc,
                    peak_local=peak_utc.astimezone(tz),
                    obscuration=e.obscuration if e.obscuration and not math.isnan(e.obscuration) else None,
                ))
        t = astronomy.Time(e.peak.time.ut + 20)

    results.sort(key=lambda x: x.peak_utc)
    return results[:count]
