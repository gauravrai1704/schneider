"""
Feature construction shared by training (app/train_forecast.py) and live
inference (app/forecast.py). Keeping one implementation guarantees the model
sees identically-built features in both places.

Solar is modelled as a *clearness index* k = GHI / clear-sky GHI, which
removes the sun-angle shape and leaves only the weather part to learn.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SOLAR_FEATURES = [
    "horizon_min", "tgt_hour_sin", "tgt_hour_cos", "doy_sin", "doy_cos",
    "cs_tgt", "nwp_k_tgt", "cloud_tgt", "k_now", "nwp_k_now", "k_prev",
]
LOAD_FEATURES = [
    "horizon_min", "tgt_hour_sin", "tgt_hour_cos", "dow", "is_weekend", "is_holiday",
    "doy_sin", "doy_cos", "temp_tgt", "rh_tgt", "load_now", "load_yday", "load_week",
]

SOLAR_HORIZONS_MIN = [60, 120, 180, 240, 300, 360]
LOAD_HORIZONS_MIN = [15, 30, 60, 120, 180, 240, 300, 360]
MIN_CLEAR_SKY = 50.0   # W/m² — below this (dawn/dusk/night) k is meaningless
K_MAX = 1.3            # cloud-edge enhancement can briefly push k above 1


def clearness(ghi, cs):
    ghi, cs = np.asarray(ghi, dtype=float), np.asarray(cs, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        k = np.where(cs >= MIN_CLEAR_SKY, ghi / cs, np.nan)
    return np.clip(k, 0, K_MAX)


def _cyc(values, period):
    rad = 2 * np.pi * np.asarray(values, dtype=float) / period
    return np.sin(rad), np.cos(rad)


def time_features(ts_ist: pd.DatetimeIndex) -> dict:
    hour = ts_ist.hour + ts_ist.minute / 60
    h_sin, h_cos = _cyc(hour, 24)
    d_sin, d_cos = _cyc(ts_ist.dayofyear, 365.25)
    return {"tgt_hour_sin": h_sin, "tgt_hour_cos": h_cos, "doy_sin": d_sin, "doy_cos": d_cos}


_holiday_cache: dict[int, set] = {}


def is_holiday(ts_ist: pd.DatetimeIndex) -> np.ndarray:
    import holidays
    out = np.zeros(len(ts_ist), dtype=int)
    for year in set(ts_ist.year):
        if year not in _holiday_cache:
            _holiday_cache[year] = set(holidays.India(years=year).keys())
    dates = ts_ist.date
    for i, d in enumerate(dates):
        out[i] = int(d in _holiday_cache[d.year])
    return out


def solar_frame(horizon_min, tgt_ist, cs_tgt, nwp_ghi_tgt, cloud_tgt,
                k_now, nwp_k_now, k_prev) -> pd.DataFrame:
    """All args are equal-length arrays (or scalars broadcast by pandas)."""
    tgt_ist = pd.DatetimeIndex(tgt_ist)
    df = pd.DataFrame({"horizon_min": np.asarray(horizon_min, dtype=float)}, index=range(len(tgt_ist)))
    for k, v in time_features(tgt_ist).items():
        df[k] = v
    df["cs_tgt"] = cs_tgt
    df["nwp_k_tgt"] = clearness(nwp_ghi_tgt, cs_tgt)
    df["cloud_tgt"] = cloud_tgt
    df["k_now"] = k_now
    df["nwp_k_now"] = nwp_k_now
    df["k_prev"] = k_prev
    return df[SOLAR_FEATURES].astype(float)


def load_frame(horizon_min, tgt_ist, temp_tgt, rh_tgt, load_now, load_yday, load_week) -> pd.DataFrame:
    tgt_ist = pd.DatetimeIndex(tgt_ist)
    df = pd.DataFrame({"horizon_min": np.asarray(horizon_min, dtype=float)}, index=range(len(tgt_ist)))
    for k, v in time_features(tgt_ist).items():
        df[k] = v
    df["dow"] = tgt_ist.dayofweek
    df["is_weekend"] = (tgt_ist.dayofweek >= 5).astype(int)
    df["is_holiday"] = is_holiday(tgt_ist)
    df["temp_tgt"] = temp_tgt
    df["rh_tgt"] = rh_tgt
    df["load_now"] = load_now
    df["load_yday"] = load_yday
    df["load_week"] = load_week
    return df[LOAD_FEATURES].astype(float)
