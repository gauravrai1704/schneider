"""
Trains the solar and feeder-load forecast models on REAL Delhi data and saves
them to app/models_store/. Fetch the data first (see data/SOURCES.md):

    python -m etl.fetch_solar && python -m etl.fetch_weather && python -m etl.fetch_load
    python -m app.train_forecast

Evaluation is honest by construction:
  - weather inputs are archived *forecasts*, not observations;
  - train/test split is by whole weeks (every 5th week held out), so the test
    set covers every season and no test hour leaks via its neighbours;
  - every model is compared against the standard baselines it must beat.
After evaluation the final model is refit on all data.
"""
from __future__ import annotations
import json
import os

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from app import config
from app.features import (
    K_MAX, LOAD_FEATURES, LOAD_HORIZONS_MIN, MIN_CLEAR_SKY, SOLAR_FEATURES, SOLAR_HORIZONS_MIN,
    clearness, load_frame, solar_frame,
)
from app.solar_geometry import clear_sky_ghi_series
from etl.common import LOAD_CSV, SOLAR_CSV, WEATHER_CSV

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models_store")
RNG = np.random.default_rng(42)
LGB_PARAMS = dict(n_estimators=600, learning_rate=0.04, num_leaves=63, min_child_samples=40,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.9, verbosity=-1, random_state=42)


def _mask(df: pd.DataFrame, cols: list[str], frac: float):
    """Randomly blank live-observation features so the model also works when
    they're unavailable at inference (no panel telemetry, SLDC unreachable).
    LightGBM handles NaN natively."""
    for c in cols:
        df.loc[RNG.random(len(df)) < frac, c] = np.nan


def _mask_jointly(df: pd.DataFrame, cols: list[str], frac: float):
    df.loc[RNG.random(len(df)) < frac, cols] = np.nan


def _week_split(ts: pd.DatetimeIndex) -> np.ndarray:
    """True for test rows: every 5th ISO week."""
    return (ts.isocalendar().week.values % 5) == 0


def _weather_on(grid_utc: pd.DatetimeIndex) -> pd.DataFrame:
    wx = pd.read_csv(WEATHER_CSV, index_col="ts_utc", parse_dates=True)
    wx = wx[~wx.index.duplicated()]
    return wx.reindex(wx.index.union(grid_utc)).interpolate(method="time", limit=4).reindex(grid_utc)


def _mae(a, b):
    m = ~(np.isnan(a) | np.isnan(b))
    return float(np.mean(np.abs(a[m] - b[m])))


# ---------------------------------------------------------------- solar
def build_solar_set() -> pd.DataFrame:
    sol = pd.read_csv(SOLAR_CSV, index_col="ts_utc", parse_dates=True)
    grid = pd.date_range(sol.index.min(), sol.index.max(), freq="1h")
    ghi = sol["ghi"].reindex(grid)
    wx = _weather_on(grid)
    cs = pd.Series(clear_sky_ghi_series(grid), index=grid)
    k = pd.Series(clearness(ghi, cs), index=grid)
    nwp_k = pd.Series(clearness(wx["nwp_ghi"], cs), index=grid)

    frames = []
    for h in SOLAR_HORIZONS_MIN:
        s = h // 60
        tgt = grid + pd.Timedelta(minutes=h)
        f = solar_frame(
            horizon_min=np.full(len(grid), h), tgt_ist=tgt.tz_convert(config.IST),
            cs_tgt=cs.shift(-s).values, nwp_ghi_tgt=wx["nwp_ghi"].shift(-s).values,
            cloud_tgt=wx["cloud_cover"].shift(-s).values,
            k_now=k.values, nwp_k_now=nwp_k.values, k_prev=k.shift(1).values,
        )
        f["target_k"] = k.shift(-s).values
        f["ghi_tgt"] = ghi.shift(-s).values
        f["nwp_ghi_tgt"] = wx["nwp_ghi"].shift(-s).values
        f["issue_ts"] = grid
        frames.append(f)
    df = pd.concat(frames, ignore_index=True)
    return df[df["cs_tgt"] >= MIN_CLEAR_SKY].dropna(subset=["target_k", "ghi_tgt"])


def _fit_solar(df: pd.DataFrame) -> tuple[lgb.LGBMRegressor, lgb.LGBMRegressor]:
    """Two models:
      obs: predicts the *change* in clearness from the panel's current reading
           (k_tgt - k_now). Short-horizon persistence is hard to beat directly;
           learning the residual on top of it beats it at every horizon.
      nwp: predicts absolute clearness from weather forecast + calendar only,
           for when there's no live reading (night, no telemetry)."""
    obs_rows = df[df["k_now"].notna()].copy()
    _mask(obs_rows, ["k_prev"], 0.25)
    obs = lgb.LGBMRegressor(**LGB_PARAMS).fit(obs_rows[SOLAR_FEATURES], obs_rows["target_k"] - obs_rows["k_now"])
    nwp_rows = df.copy()
    nwp_rows[["k_now", "k_prev"]] = np.nan
    nwp = lgb.LGBMRegressor(**LGB_PARAMS).fit(nwp_rows[SOLAR_FEATURES], nwp_rows["target_k"])
    return obs, nwp


def train_solar() -> dict:
    df = build_solar_set()
    test = _week_split(pd.DatetimeIndex(df["issue_ts"]))
    obs, nwp = _fit_solar(df[~test])

    te = df[test]
    has_obs = te["k_now"].notna().values
    te, truth = te[has_obs], te["ghi_tgt"].values[has_obs]   # compare all methods on the same rows
    cs = te["cs_tgt"].values
    pred_obs = np.clip(obs.predict(te[SOLAR_FEATURES]) + te["k_now"].values, 0, K_MAX) * cs
    no_obs = te[SOLAR_FEATURES].copy()
    no_obs[["k_now", "k_prev"]] = np.nan
    pred_nwp = np.clip(nwp.predict(no_obs), 0, K_MAX) * cs
    persistence = te["k_now"].values * cs
    raw_nwp = te["nwp_ghi_tgt"].values
    metrics = {
        "unit": "W/m² MAE on daylight hours, held-out weeks",
        "ml_with_live_panel": _mae(pred_obs, truth),
        "ml_weather_only": _mae(pred_nwp, truth),
        "baseline_persistence": _mae(persistence, truth),
        "baseline_raw_open_meteo": _mae(raw_nwp, truth),
        "by_horizon_min": {
            int(h): {"ml": _mae(pred_obs[g], truth[g]), "ml_weather_only": _mae(pred_nwp[g], truth[g]),
                     "persistence": _mae(persistence[g], truth[g]), "open_meteo": _mae(raw_nwp[g], truth[g])}
            for h in SOLAR_HORIZONS_MIN for g in [te["horizon_min"].values == h]
        },
        "n_train": int((~test).sum()), "n_test": int(has_obs.sum()),
    }

    obs, nwp = _fit_solar(df)
    joblib.dump(obs, os.path.join(MODELS_DIR, "solar_obs_model.joblib"), compress=3)
    joblib.dump(nwp, os.path.join(MODELS_DIR, "solar_nwp_model.joblib"), compress=3)
    return {"features": SOLAR_FEATURES, "horizons_min": SOLAR_HORIZONS_MIN, "metrics": metrics}


# ---------------------------------------------------------------- load
def build_load_set() -> tuple[pd.DataFrame, float]:
    ld = pd.read_csv(LOAD_CSV, index_col="ts_ist", parse_dates=True)
    y = ld[config.LOAD_DISCOM]
    y.index = y.index.tz_localize(config.IST)
    grid = pd.date_range(y.index.min(), y.index.max(), freq="15min")
    y = y.reindex(grid).interpolate(limit=2)   # bridge isolated gaps only (<=30 min)
    wx = _weather_on(grid.tz_convert("UTC"))
    temp = pd.Series(wx["temp_c"].values, index=grid)
    rh = pd.Series(wx["rh"].values, index=grid)

    frames = []
    for h in LOAD_HORIZONS_MIN:
        s = h // 15
        f = load_frame(
            horizon_min=np.full(len(grid), h), tgt_ist=grid + pd.Timedelta(minutes=h),
            temp_tgt=temp.shift(-s).values, rh_tgt=rh.shift(-s).values,
            load_now=y.values, load_yday=y.shift(96 - s).values, load_week=y.shift(672 - s).values,
        )
        f["target_mw"] = y.shift(-s).values
        f["issue_ts"] = grid
        frames.append(f)
    df = pd.concat(frames, ignore_index=True).dropna(subset=["target_mw"])
    return df, float(y.quantile(0.999))


def train_load() -> dict:
    df, peak_mw = build_load_set()
    test = _week_split(pd.DatetimeIndex(df["issue_ts"]))
    train_df = df[~test].copy()
    _mask(train_df, ["load_now", "load_yday", "load_week"], 0.3)
    _mask_jointly(train_df, ["temp_tgt", "rh_tgt"], 0.1)   # works offline too

    model = lgb.LGBMRegressor(**LGB_PARAMS)
    model.fit(train_df[LOAD_FEATURES], train_df["target_mw"])

    te = df[test]
    truth = te["target_mw"].values
    pred = model.predict(te[LOAD_FEATURES])
    calendar_only = te[LOAD_FEATURES].copy()
    calendar_only[["load_now", "load_yday", "load_week"]] = np.nan
    pred_cal = model.predict(calendar_only)
    mape = lambda p: float(np.nanmean(np.abs(p - truth) / truth) * 100)  # noqa: E731
    metrics = {
        "unit": f"{config.LOAD_DISCOM} MW, held-out weeks",
        "ml_with_live_sldc": {"mae": _mae(pred, truth), "mape_pct": mape(pred)},
        "ml_weather_calendar_only": {"mae": _mae(pred_cal, truth), "mape_pct": mape(pred_cal)},
        "baseline_persistence": {"mae": _mae(te["load_now"].values, truth), "mape_pct": mape(te["load_now"].values)},
        "baseline_same_time_yesterday": {"mae": _mae(te["load_yday"].values, truth), "mape_pct": mape(te["load_yday"].values)},
        "baseline_same_time_last_week": {"mae": _mae(te["load_week"].values, truth), "mape_pct": mape(te["load_week"].values)},
        "n_train": int((~test).sum()), "n_test": int(test.sum()),
    }

    full = df.copy()
    _mask(full, ["load_now", "load_yday", "load_week"], 0.3)
    _mask_jointly(full, ["temp_tgt", "rh_tgt"], 0.1)
    final = lgb.LGBMRegressor(**LGB_PARAMS).fit(full[LOAD_FEATURES], full["target_mw"])
    joblib.dump(final, os.path.join(MODELS_DIR, "load_model.joblib"), compress=3)
    return {"features": LOAD_FEATURES, "horizons_min": LOAD_HORIZONS_MIN, "discom": config.LOAD_DISCOM,
            "peak_mw": peak_mw, "metrics": metrics}


if __name__ == "__main__":
    os.makedirs(MODELS_DIR, exist_ok=True)
    print("Training solar model (NASA POWER + Open-Meteo archived forecasts)...")
    solar_meta = train_solar()
    print(json.dumps(solar_meta["metrics"], indent=2))
    print(f"Training load model (Delhi SLDC {config.LOAD_DISCOM} + Open-Meteo)...")
    load_meta = train_load()
    print(json.dumps(load_meta["metrics"], indent=2))
    meta = {
        "location": {"city": config.CITY, "lat": config.LATITUDE, "lon": config.LONGITUDE},
        "train_window": [config.TRAIN_START, config.TRAIN_END],
        "sources": {
            "solar": "NASA POWER hourly ALLSKY_SFC_SW_DWN",
            "weather": "Open-Meteo Historical Forecast API (archived forecasts)",
            "load": f"Delhi SLDC 5-min load, {config.LOAD_DISCOM} column",
        },
        "solar": solar_meta, "load": load_meta,
    }
    with open(os.path.join(MODELS_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print("Saved models to", MODELS_DIR)
