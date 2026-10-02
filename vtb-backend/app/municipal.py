"""
Municipal water supply windows (IST). The sump only refills inside these
windows, so the scheduler uses them to:
  - empty the sump into the overhead tank just before a window, so municipal
    water isn't turned away by a full sump;
  - tell residents when a dry sump will refill.
"""
from __future__ import annotations
from datetime import datetime, timedelta

from app.clock import to_ist
from app.config import MUNICIPAL_SUPPLY_WINDOWS


def in_window(dt: datetime) -> bool:
    t = to_ist(dt)
    h = t.hour + t.minute / 60
    return any(start <= h < end for start, end in MUNICIPAL_SUPPLY_WINDOWS)


def next_window_start(dt: datetime) -> datetime:
    """Start of the next supply window strictly after dt (today or tomorrow)."""
    t = to_ist(dt)
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in (0, 1):
        for start, _ in sorted(MUNICIPAL_SUPPLY_WINDOWS):
            candidate = day + timedelta(days=offset, hours=start)
            if candidate > t:
                return candidate
    raise RuntimeError("MUNICIPAL_SUPPLY_WINDOWS is empty")


def minutes_until_next_window(dt: datetime) -> float:
    return (next_window_start(dt) - to_ist(dt)).total_seconds() / 60
