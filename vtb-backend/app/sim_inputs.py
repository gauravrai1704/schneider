"""
Real inputs for the feeder simulator, taken from the committed training data:

  solar      one actual day of NASA POWER irradiance over Delhi from the same
             calendar month — the median-clearness day for a normal day, the
             cloudiest day for "cloudy day" mode
  base load  the average BYPL demand shape for that month (Delhi SLDC),
             normalised so its peak = 1.0

Falls back to clear-sky geometry and a typical residential curve if the CSVs
are missing, and says so in the returned description.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from app import config
from app.clock import hour_float
from app.solar_geometry import clear_sky_ghi

_PROCESSED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed")
SOLAR_CSV = os.path.join(_PROCESSED, "solar_nasa_power.csv")
LOAD_CSV = os.path.join(_PROCESSED, "load_delhi_sldc.csv")


@dataclass
class SimInputs:
    times: list[datetime]          # IST, one per step
    ghi: np.ndarray                # W/m² per step
    load_shape: np.ndarray         # 0..1 per step (1 = this month's typical peak)
    solar_source: str
    load_source: str


def _grid(day: datetime) -> list[datetime]:
    steps = int(24 * 60 / config.SIM_TIMESTEP_MIN)
    return [day + timedelta(minutes=i * config.SIM_TIMESTEP_MIN) for i in range(steps)]


@lru_cache(maxsize=4)
def _solar_by_day(month: int) -> pd.DataFrame | None:
    if not os.path.exists(SOLAR_CSV):
        return None
    s = pd.read_csv(SOLAR_CSV, index_col="ts_utc", parse_dates=True)
    s.index = s.index.tz_convert(config.IST)
    s = s[s.index.month == month]
    return s if not s.empty else None


def _solar(times: list[datetime], cloudy: bool) -> tuple[np.ndarray, str]:
    s = _solar_by_day(times[0].month)
    if s is not None:
        daily = s.groupby(s.index.date).agg(ghi=("ghi", "sum"), clr=("ghi_clr", "sum"))
        daily = daily[daily["clr"] > 0]
        daily["k"] = daily["ghi"] / daily["clr"]
        pick = daily["k"].idxmin() if cloudy else (daily["k"] - daily["k"].median()).abs().idxmin()
        hours = s[s.index.date == pick]["ghi"]
        # Same time-of-day on the simulated date, interpolated hourly -> per step
        x = np.array([h.hour + h.minute / 60 for h in hours.index])
        y = hours.values
        tod = np.array([hour_float(t) for t in times])
        ghi = np.interp(tod, np.concatenate([[0], x, [24]]), np.concatenate([[0], y, [0]]))
        label = f"NASA POWER irradiance, {pick:%d %b %Y} ({'cloudiest' if cloudy else 'typical'} day that month)"
        return np.clip(ghi, 0, None), label
    cs = np.array([clear_sky_ghi(t) for t in times])
    if cloudy:
        cs = cs * np.where([10 <= hour_float(t) <= 15 for t in times], 0.3, 1.0)
    return cs, "clear-sky model (NASA data unavailable)"


@lru_cache(maxsize=4)
def _load_profile(month: int) -> pd.Series | None:
    if not os.path.exists(LOAD_CSV):
        return None
    ld = pd.read_csv(LOAD_CSV, index_col="ts_ist", parse_dates=True)
    y = ld[ld.index.month == month][config.LOAD_DISCOM].dropna()
    if y.empty:
        return None
    prof = y.groupby(y.index.hour * 60 + y.index.minute).mean()
    return prof / prof.max()


def _load(times: list[datetime]) -> tuple[np.ndarray, str]:
    prof = _load_profile(times[0].month)
    if prof is not None:
        x = np.append(prof.index.values, 1440)
        y = np.append(prof.values, prof.values[0])   # wrap midnight
        tod = np.array([t.hour * 60 + t.minute for t in times])
        return np.interp(tod, x, y), f"Delhi SLDC {config.LOAD_DISCOM} average demand shape, {times[0]:%B}"
    from app.forecast import _feeder_load_curve_w
    shape = np.array([_feeder_load_curve_w(hour_float(t)) for t in times])
    return shape / shape.max(), "typical residential curve (SLDC data unavailable)"


def build_inputs(day: datetime, cloudy: bool) -> SimInputs:
    times = _grid(day)
    ghi, solar_src = _solar(times, cloudy)
    shape, load_src = _load(times)
    return SimInputs(times, ghi, shape, solar_src, load_src)
