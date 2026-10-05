"""
Single source of "now". Everything time-of-day dependent (solar curve,
water draw, tariffs) must use IST, never the server's UTC clock.

Demo clock: set VTB_DEMO_TIME=HH:MM (e.g. 12:30) to start the system at that
time of day and let it run forward from there — for presenting a "sunny
midday" demo in an evening slot. Forecasts still use real weather data for
that hour. /sources reports it and the dashboard shows a "Demo clock" badge.
"""
import os
from datetime import datetime, timedelta

from app.config import IST

DEMO_TIME = os.environ.get("VTB_DEMO_TIME") or None


def _demo_offset() -> timedelta:
    if not DEMO_TIME:
        return timedelta(0)
    hh, mm = (int(x) for x in DEMO_TIME.split(":"))
    real = datetime.now(IST)
    return real.replace(hour=hh, minute=mm, second=0, microsecond=0) - real


_OFFSET = _demo_offset()


def now_ist() -> datetime:
    return datetime.now(IST) + _OFFSET


def to_ist(dt: datetime) -> datetime:
    """Naive datetimes are assumed to already be IST."""
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def hour_float(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600
