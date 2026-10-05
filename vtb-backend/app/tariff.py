"""
Time-of-day electricity tariff (see config for the source and assumptions).
"""
from __future__ import annotations
from datetime import datetime

from app.clock import to_ist
from app.config import (
    TARIFF_NORMAL_INR_PER_KWH, TARIFF_PEAK_FACTOR, TARIFF_PEAK_HOURS, TARIFF_SOLAR_FACTOR, TARIFF_SOLAR_HOURS,
)


def period(dt: datetime) -> str:
    h = to_ist(dt).hour
    if TARIFF_SOLAR_HOURS[0] <= h < TARIFF_SOLAR_HOURS[1]:
        return "solar"
    if TARIFF_PEAK_HOURS[0] <= h < TARIFF_PEAK_HOURS[1]:
        return "peak"
    return "normal"


def factor(dt: datetime) -> float:
    return {"solar": TARIFF_SOLAR_FACTOR, "peak": TARIFF_PEAK_FACTOR}.get(period(dt), 1.0)


def rate_inr_per_kwh(dt: datetime) -> float:
    return TARIFF_NORMAL_INR_PER_KWH * factor(dt)


def describe() -> dict:
    return {
        "normal_inr_per_kwh": TARIFF_NORMAL_INR_PER_KWH,
        "solar_hours": f"{TARIFF_SOLAR_HOURS[0]:02d}:00-{TARIFF_SOLAR_HOURS[1]:02d}:00",
        "solar_discount_pct": round(100 * (1 - TARIFF_SOLAR_FACTOR)),
        "peak_hours": f"{TARIFF_PEAK_HOURS[0]:02d}:00-{TARIFF_PEAK_HOURS[1]:02d}:00",
        "peak_surcharge_pct": round(100 * (TARIFF_PEAK_FACTOR - 1)),
        "basis": "DERC domestic slab 401-800 units; ToD per Electricity (Rights of Consumers) Amendment Rules 2023",
    }
