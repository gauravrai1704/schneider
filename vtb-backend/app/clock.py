"""
Single source of "now". Everything time-of-day dependent (solar curve,
water draw, tariffs) must use IST, never the server's UTC clock.
"""
from datetime import datetime

from app.config import IST


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    """Naive datetimes are assumed to already be IST."""
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def hour_float(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600
