"""
Feeder State of Charge — the virtual battery's numbers for the DISCOM.

  soc_kwh                  pumping energy that can still be absorbed right now: for each
                           building, the water it could move (limited by empty tank space AND
                           by water actually available in its sump) x energy per litre
  sheddable_w              pump load that a Pump Pause would remove this instant
  pause_minutes_available  how long every pump could stay off before the first tank on the
                           feeder reaches its safe minimum, at forecast water demand
"""
from __future__ import annotations
from datetime import datetime, timedelta

from app.config import (
    ENERGY_PER_LITRE_WH, SAFE_MIN_LEVEL_PCT, SUMP_CAPACITY_LITRES, SUMP_MIN_LEVEL_PCT, TANK_CAPACITY_LITRES,
)
from app.water import draw_litres_per_hr

MAX_PAUSE_MIN = 24 * 60


def fillable_litres(level_pct: float, sump_level_pct: float | None) -> float:
    tank_space = TANK_CAPACITY_LITRES * max(0.0, 100 - level_pct) / 100
    if sump_level_pct is None:
        return tank_space
    sump_water = SUMP_CAPACITY_LITRES * max(0.0, sump_level_pct - SUMP_MIN_LEVEL_PCT) / 100
    return min(tank_space, sump_water)


def minutes_until_safe_min(building_id: str, level_pct: float, now: datetime) -> float:
    reserve_l = TANK_CAPACITY_LITRES * max(0.0, level_pct - SAFE_MIN_LEVEL_PCT) / 100
    # conservative: the heavier of now and the next hour's demand
    draw = max(draw_litres_per_hr(now, building_id), draw_litres_per_hr(now + timedelta(hours=1), building_id))
    return MAX_PAUSE_MIN if draw <= 0 else min(MAX_PAUSE_MIN, reserve_l / draw * 60)


def feeder_soc(tanks: list[dict], now: datetime) -> dict:
    """tanks: latest telemetry dicts with building_id, level_pct, sump_level_pct, pump_on, pump_w."""
    soc_l = sum(fillable_litres(t["level_pct"], t.get("sump_level_pct")) for t in tanks)
    soc_kwh = soc_l * ENERGY_PER_LITRE_WH / 1000
    max_kwh = len(tanks) * TANK_CAPACITY_LITRES * ENERGY_PER_LITRE_WH / 1000
    running = [t for t in tanks if t.get("pump_on")]
    pause_min = min((minutes_until_safe_min(t["building_id"], t["level_pct"], now) for t in tanks), default=None)
    return {
        "soc_kwh": round(soc_kwh, 2),
        "soc_pct_of_max": round(100 * soc_kwh / max_kwh, 1) if max_kwh else 0.0,
        "tanks_reporting": len(tanks),
        "pumps_running": len(running),
        "sheddable_w": round(sum(float(t.get("pump_w") or 0) for t in running), 1),
        "pause_minutes_available": round(pause_min) if pause_min is not None else None,
    }
