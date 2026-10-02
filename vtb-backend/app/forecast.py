"""
Forecasting layer.

Two backends, same function signatures either way:
  - ML (preferred): LightGBM models trained by app/train_forecast.py on
    synthetic history (app/data_gen.py), loaded from app/models_store/.
  - Heuristic fallback: seasonal-naive curves, used automatically if the
    models haven't been trained yet (fresh clone) or fail to load.

Nothing downstream (scheduler.py, simulator.py, main.py) needs to know or
care which backend is active.
"""
from __future__ import annotations
import math
import os
import numpy as np
from datetime import datetime, timedelta

from app.water import water_use_forecast  # noqa: F401  (re-exported for existing callers)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models_store")
_solar_model = None
_load_model = None

try:
    import joblib
    _solar_path = os.path.join(_MODELS_DIR, "solar_cloud_model.joblib")
    _load_path = os.path.join(_MODELS_DIR, "load_model.joblib")
    if os.path.exists(_solar_path):
        _solar_model = joblib.load(_solar_path)
    if os.path.exists(_load_path):
        _load_model = joblib.load(_load_path)
except ImportError:
    pass  # joblib/lightgbm not installed -> heuristic-only mode, still fully functional

USING_ML_SOLAR = _solar_model is not None
USING_ML_LOAD = _load_model is not None


def _cyclical(hour_float: float) -> tuple[float, float]:
    radians = 2 * math.pi * hour_float / 24
    return math.sin(radians), math.cos(radians)


def _solar_curve_w(hour_float: float, peak_w: float = 600.0) -> float:
    """Idealised clear-sky solar curve: 0 before 6am/after 6pm, bell-shaped
    between, peaking near midday. Used as the 'clear sky' baseline that
    cloud cover (from live lux/solar_w readings) discounts against."""
    sunrise, sunset = 6.0, 18.0
    if hour_float <= sunrise or hour_float >= sunset:
        return 0.0
    x = (hour_float - sunrise) / (sunset - sunrise)  # 0..1 across the day
    return peak_w * math.sin(math.pi * x)


def solar_forecast(now: datetime, horizons_min: list[int], recent_cloud_factor: float = 1.0) -> list[dict]:
    """recent_cloud_factor: ratio of observed solar_w to clear-sky solar_w
    over the last few readings (1.0 = clear, <1.0 = clouds cutting output).

    ML mode: predicts how that cloud factor evolves over each horizon
    (clouds tend to persist short-term, clear/thicken over longer horizons —
    the model learns this decay from synthetic history). Heuristic fallback:
    naively projects the same cloud factor forward unchanged."""
    out = []
    for h in horizons_min:
        t = now + timedelta(minutes=h)
        hour_float = t.hour + t.minute / 60
        clear_sky = _solar_curve_w(hour_float)

        if USING_ML_SOLAR:
            import pandas as pd
            sin_h, cos_h = _cyclical(now.hour + now.minute / 60)
            features = pd.DataFrame([{
                "hour_sin": sin_h, "hour_cos": cos_h, "day_of_week": now.weekday(),
                "horizon_min": h, "recent_cloud_factor": recent_cloud_factor,
            }])
            predicted_cloud = float(np.clip(_solar_model.predict(features)[0], 0.0, 1.0))
            solar_w = clear_sky * predicted_cloud
        else:
            solar_w = clear_sky * recent_cloud_factor

        out.append({"horizon_min": h, "solar_w": round(solar_w, 1)})
    return out


def _feeder_load_curve_w(hour_float: float, base_w: float = 400.0, peak_w: float = 1200.0) -> float:
    """Rough residential feeder demand shape: morning bump (~7-9am),
    evening peak (~7-10pm), lower overnight."""
    morning = math.exp(-((hour_float - 8) ** 2) / 2) * (peak_w - base_w) * 0.6
    evening = math.exp(-((hour_float - 20) ** 2) / 3) * (peak_w - base_w)
    return base_w + morning + evening


def load_forecast(now: datetime, horizons_min: list[int]) -> list[dict]:
    out = []
    for h in horizons_min:
        t = now + timedelta(minutes=h)
        hour_float = t.hour + t.minute / 60

        if USING_ML_LOAD:
            import pandas as pd
            sin_h, cos_h = _cyclical(hour_float)
            is_weekend = int(t.weekday() >= 5)
            features = pd.DataFrame([{
                "hour_sin": sin_h, "hour_cos": cos_h, "day_of_week": t.weekday(), "is_weekend": is_weekend,
            }])
            feeder_load_w = float(max(0.0, _load_model.predict(features)[0]))
        else:
            feeder_load_w = _feeder_load_curve_w(hour_float)

        out.append({"horizon_min": h, "feeder_load_w": round(feeder_load_w, 1)})
    return out


def combined_forecast(now: datetime, horizons_min: list[int] | None = None, cloud_factor: float = 1.0) -> list[dict]:
    horizons_min = horizons_min or [0, 15, 30, 60]
    solar = {f["horizon_min"]: f["solar_w"] for f in solar_forecast(now, horizons_min, cloud_factor)}
    load = {f["horizon_min"]: f["feeder_load_w"] for f in load_forecast(now, horizons_min)}
    return [
        {"horizon_min": h, "solar_w": solar[h], "feeder_load_w": load[h]}
        for h in horizons_min
    ]


def is_predicted_dip(now: datetime, lookahead_min: int, threshold_w: float, cloud_factor: float = 1.0) -> bool:
    """True if solar is forecast to drop below threshold within the lookahead window."""
    points = solar_forecast(now, [lookahead_min], cloud_factor)
    return points[0]["solar_w"] < threshold_w
