"""
Trains two LightGBM models on synthetic history (app/data_gen.py) and saves
them to app/models_store/. Run once:

    python3 -m app.train_forecast

app/forecast.py loads these automatically if present, falling back to the
pure heuristic if the files are missing (e.g. fresh clone before training).

Swap `generate_solar_history` / `generate_load_history` for loaders of real
NASA POWER / DISCOM data later — everything downstream (feature building,
training, saving) stays the same as long as the column names match.
"""
from __future__ import annotations
import json
import os
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import joblib

from app.data_gen import generate_solar_history, generate_load_history

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models_store")
HORIZONS_MIN = [0, 15, 30, 60, 90, 120]


def _cyclical(hour_float: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    radians = 2 * np.pi * hour_float / 24
    return np.sin(radians), np.cos(radians)


def build_solar_training_set(df: pd.DataFrame) -> pd.DataFrame:
    """For each timestep and each horizon, the example is:
    'given conditions now, predict the cloud_factor `horizon` minutes ahead'.
    This is what solar_forecast() needs at inference time."""
    examples = []
    cloud = df["cloud_factor"].values
    hour = df["hour"].values
    dow = df["day_of_week"].values
    n = len(df)
    step_min = (df["ts"].iloc[1] - df["ts"].iloc[0]).total_seconds() / 60

    for h in HORIZONS_MIN:
        shift = int(h / step_min)
        if shift >= n:
            continue
        future_cloud = cloud[shift:]
        cur_hour = hour[: n - shift]
        cur_cloud = cloud[: n - shift]
        cur_dow = dow[: n - shift]
        sin_h, cos_h = _cyclical(cur_hour)
        examples.append(pd.DataFrame({
            "hour_sin": sin_h, "hour_cos": cos_h, "day_of_week": cur_dow,
            "horizon_min": h, "recent_cloud_factor": cur_cloud,
            "target_cloud_factor": future_cloud,
        }))
    return pd.concat(examples, ignore_index=True)


def build_load_training_set(df: pd.DataFrame) -> pd.DataFrame:
    hour = df["hour"].values
    sin_h, cos_h = _cyclical(hour)
    return pd.DataFrame({
        "hour_sin": sin_h, "hour_cos": cos_h,
        "day_of_week": df["day_of_week"].values, "is_weekend": df["is_weekend"].values,
        "target_load_w": df["feeder_load_w"].values,
    })


def train_solar_model():
    print("Generating synthetic solar history...")
    df = generate_solar_history(days=120)
    train_df = build_solar_training_set(df)
    features = ["hour_sin", "hour_cos", "day_of_week", "horizon_min", "recent_cloud_factor"]
    X, y = train_df[features], train_df["target_cloud_factor"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.15, random_state=42)

    model = lgb.LGBMRegressor(n_estimators=200, max_depth=6, learning_rate=0.05, verbosity=-1)
    model.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, model.predict(X_test))
    print(f"Solar cloud-factor model MAE: {mae:.4f} (cloud_factor is 0-1 scale)")

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model, os.path.join(MODELS_DIR, "solar_cloud_model.joblib"))
    return {"features": features, "mae": mae}


def train_load_model():
    print("Generating synthetic load history...")
    df = generate_load_history(days=120)
    train_df = build_load_training_set(df)
    features = ["hour_sin", "hour_cos", "day_of_week", "is_weekend"]
    X, y = train_df[features], train_df["target_load_w"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.15, random_state=42)

    model = lgb.LGBMRegressor(n_estimators=200, max_depth=6, learning_rate=0.05, verbosity=-1)
    model.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, model.predict(X_test))
    print(f"Feeder load model MAE: {mae:.1f} W")

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model, os.path.join(MODELS_DIR, "load_model.joblib"))
    return {"features": features, "mae": mae}


if __name__ == "__main__":
    solar_meta = train_solar_model()
    load_meta = train_load_model()
    with open(os.path.join(MODELS_DIR, "metadata.json"), "w") as f:
        json.dump({"solar": solar_meta, "load": load_meta}, f, indent=2)
    print("Saved models to", MODELS_DIR)
