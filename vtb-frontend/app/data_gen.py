"""
Generates synthetic historical data to train the forecast models on, since
we don't have real feeder/solar history yet. Built from the same physical
shapes as app/forecast.py's heuristics, but with autocorrelated weather
regimes and day-to-day variation so the ML models learn something beyond
just re-deriving the hand-written curve.

Swap this for real NASA POWER / DISCOM data the moment it's available —
train_forecast.py doesn't care where the CSV came from, only its columns.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from app.forecast import _solar_curve_w, _feeder_load_curve_w

RNG = np.random.default_rng(42)


def generate_solar_history(days: int = 120, timestep_min: int = 5) -> pd.DataFrame:
    """One row per timestep with a ground-truth cloud_factor and solar_w.
    Weather regime persists for a random 2-8hr block per day (clear /
    partly cloudy / overcast), with an AR(1) wobble on top so it's not a
    step function."""
    rows = []
    start = datetime(2026, 1, 1)
    steps_per_day = int(24 * 60 / timestep_min)

    for day in range(days):
        day_start = start + timedelta(days=day)
        regime = RNG.choice(["clear", "partly_cloudy", "overcast"], p=[0.45, 0.4, 0.15])
        regime_mean = {"clear": 0.95, "partly_cloudy": 0.65, "overcast": 0.25}[regime]
        cloud_factor = regime_mean
        for step in range(steps_per_day):
            t = day_start + timedelta(minutes=step * timestep_min)
            hour_float = t.hour + t.minute / 60
            # AR(1) wobble around the regime mean, clipped to [0.05, 1.0]
            cloud_factor = 0.85 * cloud_factor + 0.15 * regime_mean + RNG.normal(0, 0.05)
            cloud_factor = float(np.clip(cloud_factor, 0.05, 1.0))
            clear_sky = _solar_curve_w(hour_float)
            solar_w = clear_sky * cloud_factor + RNG.normal(0, 5) if clear_sky > 0 else 0.0
            rows.append({
                "ts": t, "hour": hour_float, "day_of_week": t.weekday(),
                "cloud_factor": cloud_factor, "clear_sky_w": clear_sky,
                "solar_w": max(0.0, solar_w),
            })
    return pd.DataFrame(rows)


def generate_load_history(days: int = 120, timestep_min: int = 5) -> pd.DataFrame:
    """One row per timestep with feeder_load_w, including weekday/weekend
    shape differences and a per-day random scale (e.g. festival/holiday
    days with different demand)."""
    rows = []
    start = datetime(2026, 1, 1)
    steps_per_day = int(24 * 60 / timestep_min)

    for day in range(days):
        day_start = start + timedelta(days=day)
        is_weekend = day_start.weekday() >= 5
        daily_scale = float(RNG.normal(1.0 if not is_weekend else 0.9, 0.08))
        for step in range(steps_per_day):
            t = day_start + timedelta(minutes=step * timestep_min)
            hour_float = t.hour + t.minute / 60
            base = _feeder_load_curve_w(hour_float)
            if is_weekend:
                # weekends: flatter morning bump, slightly later evening peak
                base = _feeder_load_curve_w(hour_float - 0.5) * 0.9 + 50
            load_w = base * daily_scale + RNG.normal(0, 15)
            rows.append({
                "ts": t, "hour": hour_float, "day_of_week": t.weekday(),
                "is_weekend": int(is_weekend), "feeder_load_w": max(0.0, load_w),
            })
    return pd.DataFrame(rows)
