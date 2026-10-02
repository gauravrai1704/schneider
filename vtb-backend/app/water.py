"""
Per-building water demand model.

No public per-building consumption data exists for Indian cities, so this is
SYNTHETIC — but anchored to the CPHEEO design norm (135 litres per capita per
day for urban supply) and the typical Indian diurnal pattern: a sharp
morning peak (bathing, cooking before work/school), a smaller evening peak,
light daytime use and near-zero at night.

Everything is deterministic per building id (crc32, not hash(), which is
randomised per Python process) so the demo replays identically.
"""
from __future__ import annotations
import math
import zlib
from datetime import datetime, timedelta

from app.clock import hour_float, to_ist
from app.config import PERSONS_PER_BUILDING, WATER_LPCD

# (centre hour, width in hours, share of daily volume)
_PEAKS = [(7.5, 1.2, 0.45), (19.5, 1.5, 0.30), (13.0, 3.0, 0.20)]
_NIGHT_SHARE = 0.05


def _shape(h: float) -> float:
    """Unnormalised demand density at hour-of-day h (wraps around midnight)."""
    total = _NIGHT_SHARE / 24
    for centre, width, share in _PEAKS:
        d = min(abs(h - centre), 24 - abs(h - centre))
        total += share * math.exp(-0.5 * (d / width) ** 2) / (width * math.sqrt(2 * math.pi))
    return total


# Normalise so the shape integrates to exactly 1 over a day
_NORM = sum(_shape(i / 60) for i in range(24 * 60)) / 60


def _building_params(building_id: str) -> tuple[float, float]:
    """Deterministic per-building (phase shift in hours, size multiplier)."""
    h = zlib.crc32(building_id.encode())
    phase = ((h % 61) - 30) / 60            # -0.5 .. +0.5 hr
    size = 0.8 + ((h >> 8) % 41) / 100      # 0.8 .. 1.2x household size
    return phase, size


def daily_litres(building_id: str) -> float:
    _, size = _building_params(building_id)
    return WATER_LPCD * PERSONS_PER_BUILDING * size


def draw_litres_per_hr(t: datetime, building_id: str) -> float:
    phase, _ = _building_params(building_id)
    h = (hour_float(to_ist(t)) - phase) % 24
    return daily_litres(building_id) * _shape(h) / _NORM


def water_use_forecast(now: datetime, building_id: str, horizons_min: list[int] | None = None) -> list[dict]:
    horizons_min = horizons_min or [0, 15, 30, 60]
    return [
        {"horizon_min": h,
         "litres_per_hr": round(draw_litres_per_hr(now + timedelta(minutes=h), building_id), 2)}
        for h in horizons_min
    ]
