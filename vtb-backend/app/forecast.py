"""
Forecasting layer: solar output and feeder load for the next 0-6 hours.

Each forecast degrades gracefully and reports which path produced it:

  solar_source
    "ml+open-meteo+panel"    LightGBM (trained on NASA POWER) predicting the change from
                              the panel's current reading, using the live Open-Meteo forecast
    "ml+open-meteo"          same, weather-only model (no live panel reading)
    "open-meteo"             raw Open-Meteo forecast (no trained model)
    "clear-sky-persistence"  clear-sky curve x current panel clearness (no weather data)

  load_source
    "ml+sldc-live"           LightGBM (trained on Delhi SLDC) with live SLDC lags
    "ml-calendar-weather"    same model, live load unavailable
    "heuristic"              hand-shaped residential curve (no trained model)

Nothing downstream (scheduler.py, simulator.py, main.py) needs to know which
path is active.
"""
from __future__ import annotations
import json
import math
import os
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from app import config
from app.clock import hour_float, to_ist
from app.features import K_MAX, MIN_CLEAR_SKY, SOLAR_HORIZONS_MIN, clearness, load_frame, solar_frame
from app.live_data import grid, weather
from app.solar_geometry import clear_sky_ghi
from app.water import water_use_forecast  # noqa: F401  (re-exported for existing callers)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models_store")
_solar_obs_model = None
_solar_nwp_model = None
_load_model = None
_meta: dict = {}

try:
    import joblib
    if os.path.exists(os.path.join(_MODELS_DIR, "solar_obs_model.joblib")):
        _solar_obs_model = joblib.load(os.path.join(_MODELS_DIR, "solar_obs_model.joblib"))
        _solar_nwp_model = joblib.load(os.path.join(_MODELS_DIR, "solar_nwp_model.joblib"))
    if os.path.exists(os.path.join(_MODELS_DIR, "load_model.joblib")):
        _load_model = joblib.load(os.path.join(_MODELS_DIR, "load_model.joblib"))
    with open(os.path.join(_MODELS_DIR, "metadata.json")) as f:
        _meta = json.load(f)
except (ImportError, OSError, ValueError):
    pass  # heuristic-only mode, still fully functional

USING_ML_SOLAR = _solar_obs_model is not None and _solar_nwp_model is not None
USING_ML_LOAD = _load_model is not None and "peak_mw" in _meta.get("load", {})
LOAD_PEAK_MW = _meta.get("load", {}).get("peak_mw")


def model_info() -> dict:
    return {"ml_solar": USING_ML_SOLAR, "ml_load": USING_ML_LOAD,
            "train_window": _meta.get("train_window"), "sources": _meta.get("sources"),
            "solar_metrics": _meta.get("solar", {}).get("metrics"),
            "load_metrics": _meta.get("load", {}).get("metrics")}


# ---------------------------------------------------------------- solar
def clear_sky_w(dt: datetime) -> float:
    """Panel output under a clear sky at this instant (demo watts)."""
    return clear_sky_ghi(dt) / 1000 * config.SOLAR_PEAK_W


def panel_clearness(solar_w: float, dt: datetime) -> float | None:
    """Observed clearness index from the panel reading; None at night/dawn."""
    cs = clear_sky_ghi(dt)
    if cs < MIN_CLEAR_SKY:
        return None
    return float(np.clip(solar_w / config.SOLAR_PEAK_W * 1000 / cs, 0, K_MAX))


def current_sky_w(dt: datetime) -> float:
    """Best estimate of real panel output right now: live Open-Meteo irradiance
    if available, else clear sky. Used by the mock generator."""
    wx = weather.at(pd.DatetimeIndex([pd.Timestamp(to_ist(dt))]).tz_convert("UTC"))
    if wx is not None and not np.isnan(wx["nwp_ghi"].iloc[0]):
        return float(wx["nwp_ghi"].iloc[0]) / 1000 * config.SOLAR_PEAK_W
    return clear_sky_w(dt)


@lru_cache(maxsize=512)
def _k_curve(issue_minute: str, k_now: float | None, weather_version: float) -> tuple[str, dict[int, float]]:
    """Clearness index at horizons 0, 60, ..., 360 min from issue time.
    Cached per minute / panel reading / weather refresh — the scheduler asks
    many times a second."""
    now = datetime.fromisoformat(issue_minute)
    horizons = [0] + SOLAR_HORIZONS_MIN
    times = pd.DatetimeIndex([pd.Timestamp(now + timedelta(minutes=h)) for h in horizons]).tz_convert("UTC")
    wx = weather.at(times)
    cs = np.array([clear_sky_ghi(t.to_pydatetime()) for t in times])
    k_obs = np.nan if k_now is None else k_now

    if wx is None or wx["nwp_ghi"].isna().all():
        k = 1.0 if k_now is None else k_now
        return "clear-sky-persistence", {h: k for h in horizons}

    nwp_k = clearness(wx["nwp_ghi"].values, cs)
    if not USING_ML_SOLAR:
        return "open-meteo", {h: (float(v) if not np.isnan(v) else 1.0) for h, v in zip(horizons, nwp_k)}

    feats = solar_frame(
        horizon_min=horizons[1:], tgt_ist=times[1:].tz_convert(config.IST),
        cs_tgt=cs[1:], nwp_ghi_tgt=wx["nwp_ghi"].values[1:], cloud_tgt=wx["cloud_cover"].values[1:],
        k_now=k_obs, nwp_k_now=nwp_k[0], k_prev=np.nan,
    )
    if k_now is not None:
        pred = np.clip(_solar_obs_model.predict(feats) + k_now, 0, K_MAX)
        source, k0 = "ml+open-meteo+panel", k_now
    else:
        pred = np.clip(_solar_nwp_model.predict(feats), 0, K_MAX)
        source, k0 = "ml+open-meteo", (nwp_k[0] if not np.isnan(nwp_k[0]) else float(pred[0]))
    return source, {0: float(k0), **{h: float(p) for h, p in zip(horizons[1:], pred)}}


def solar_forecast(now: datetime, horizons_min: list[int], recent_cloud_factor: float | None = None) -> list[dict]:
    """recent_cloud_factor: the panel's current clearness index (observed /
    clear-sky output; 1.0 = clear). None if unknown (night, no telemetry)."""
    now = to_ist(now)
    minute = now.replace(second=0, microsecond=0)
    k_now = None if recent_cloud_factor is None else round(float(recent_cloud_factor), 2)
    source, k_at = _k_curve(minute.isoformat(), k_now, weather.fetched_at)
    knots = sorted(k_at)

    out = []
    for h in horizons_min:
        t = now + timedelta(minutes=h)
        k = float(np.interp(h, knots, [k_at[x] for x in knots]))
        if h > knots[-1]:  # beyond model horizon: raw weather forecast
            wx = weather.at(pd.DatetimeIndex([pd.Timestamp(t)]).tz_convert("UTC"))
            if wx is not None and not np.isnan(wx["nwp_ghi"].iloc[0]):
                k = float(clearness(wx["nwp_ghi"].values, [clear_sky_ghi(t)])[0])
                k = 1.0 if np.isnan(k) else k
        out.append({"horizon_min": h, "solar_w": round(k * clear_sky_w(t), 1), "source": source})
    return out


def is_predicted_dip(now: datetime, lookahead_min: int, threshold_w: float, cloud_factor: float | None = 1.0) -> bool:
    """True if solar is forecast to drop below threshold within the lookahead window."""
    points = solar_forecast(now, [lookahead_min], cloud_factor)
    return points[0]["solar_w"] < threshold_w


# ---------------------------------------------------------------- load
def _feeder_load_curve_w(hour_float: float, base_w: float = 400.0, peak_w: float = 1200.0) -> float:
    """Last-resort residential feeder shape: morning bump, evening peak."""
    morning = math.exp(-((hour_float - 8) ** 2) / 2) * (peak_w - base_w) * 0.6
    evening = math.exp(-((hour_float - 20) ** 2) / 3) * (peak_w - base_w)
    return base_w + morning + evening


def _mw_to_feeder_w(mw: float) -> float:
    return mw / LOAD_PEAK_MW * config.FEEDER_PEAK_W


def load_forecast(now: datetime, horizons_min: list[int]) -> list[dict]:
    now = to_ist(now)
    if not USING_ML_LOAD:
        return [{"horizon_min": h, "source": "heuristic", "discom_load_mw": None,
                 "feeder_load_w": round(_feeder_load_curve_w(hour_float(now + timedelta(minutes=h))), 1)}
                for h in horizons_min]

    latest = grid.latest()
    load_now = latest[1] if latest else np.nan
    source = "ml+sldc-live" if latest else "ml-calendar-weather"
    tgts = [now + timedelta(minutes=h) for h in horizons_min]
    tgt_idx = pd.DatetimeIndex([pd.Timestamp(t) for t in tgts])
    wx = weather.at(tgt_idx.tz_convert("UTC"))
    lag = lambda t: grid.value_at(t) if latest else None  # noqa: E731
    feats = load_frame(
        horizon_min=horizons_min, tgt_ist=tgt_idx,
        temp_tgt=wx["temp_c"].values if wx is not None else np.nan,
        rh_tgt=wx["rh"].values if wx is not None else np.nan,
        load_now=load_now,
        load_yday=[lag(t - timedelta(days=1)) or np.nan for t in tgts],
        load_week=[lag(t - timedelta(days=7)) or np.nan for t in tgts],
    )
    mw = _load_model.predict(feats)
    out = []
    for h, m in zip(horizons_min, mw):
        if h == 0 and latest:
            m = load_now
        out.append({"horizon_min": h, "source": source, "discom_load_mw": round(float(m), 1),
                    "feeder_load_w": round(_mw_to_feeder_w(float(m)), 1)})
    return out


def combined_forecast(now: datetime, horizons_min: list[int] | None = None, cloud_factor: float | None = None) -> list[dict]:
    horizons_min = horizons_min or [0, 15, 30, 60]
    solar = solar_forecast(now, horizons_min, cloud_factor)
    load = load_forecast(now, horizons_min)
    return [
        {"horizon_min": s["horizon_min"], "solar_w": s["solar_w"], "feeder_load_w": l["feeder_load_w"],
         "discom_load_mw": l["discom_load_mw"], "solar_source": s["source"], "load_source": l["source"]}
        for s, l in zip(solar, load)
    ]
