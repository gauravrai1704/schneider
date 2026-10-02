"""
Clear-sky irradiance from sun position — replaces the old fixed 6am-6pm
sine curve, so sunrise/sunset and peak height follow the real season.

Solar position: NOAA's simplified equations (accurate to ~0.5°).
Clear-sky GHI: Haurwitz (1945), GHI = 1098·cosZ·exp(-0.057/cosZ) W/m².
"""
from __future__ import annotations
import math
from datetime import datetime, timezone

import numpy as np

from app.clock import to_ist
from app.config import LATITUDE, LONGITUDE


def _zenith_cos(doy, utc_hours, lat=LATITUDE, lon=LONGITUDE):
    """cos(solar zenith). Works on floats or numpy arrays."""
    g = 2 * np.pi / 365 * (doy - 1 + (utc_hours - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    true_solar_min = utc_hours * 60 + eqtime + 4 * lon
    hour_angle = np.radians(true_solar_min / 4 - 180)
    lat_r = math.radians(lat)
    return np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hour_angle)


def _haurwitz(cos_z):
    cos_z = np.asarray(cos_z, dtype=float)
    safe = np.where(cos_z > 0.01, cos_z, 1.0)
    return np.where(cos_z > 0.01, 1098.0 * cos_z * np.exp(-0.057 / safe), 0.0)


def clear_sky_ghi(dt: datetime) -> float:
    """Clear-sky global horizontal irradiance (W/m²) at this instant."""
    utc = to_ist(dt).astimezone(timezone.utc).utctimetuple()
    utc_hours = utc.tm_hour + utc.tm_min / 60 + utc.tm_sec / 3600
    return float(_haurwitz(_zenith_cos(utc.tm_yday, utc_hours)))


def clear_sky_ghi_series(ts_utc) -> np.ndarray:
    """Vectorised version for a pandas DatetimeIndex/Series in UTC."""
    import pandas as pd
    ts = pd.DatetimeIndex(ts_utc)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC")
    utc_hours = ts.hour + ts.minute / 60 + ts.second / 3600
    return _haurwitz(_zenith_cos(ts.dayofyear.values, np.asarray(utc_hours)))
