"""
Downloads archived *forecasts* (not observations) for Delhi from Open-Meteo's
Historical Forecast API (https://open-meteo.com — public, no key). Training
on what the weather model predicted at the time, rather than what actually
happened, means the ML learns to correct real forecast errors and is
evaluated only on information that would genuinely be available live.

    python -m etl.fetch_weather [START END]

Output: data/processed/weather_openmeteo.csv
  ts_utc       hour (UTC)
  nwp_ghi      forecast shortwave radiation, W/m²
  cloud_cover  forecast total cloud cover, %
  temp_c       forecast 2 m temperature, °C
  rh           forecast 2 m relative humidity, %
"""
from __future__ import annotations
import os
import sys

import pandas as pd

from app import config
from etl.common import PROCESSED_DIR, WEATHER_CSV, get

HOURLY_VARS = "shortwave_radiation,cloud_cover,temperature_2m,relative_humidity_2m"


def parse_hourly(hourly: dict) -> pd.DataFrame:
    """Open-Meteo `hourly` block (GMT) -> tidy frame. Shared with the live feed.

    Temperature, humidity and cloud are instantaneous values at the hour;
    radiation is the mean over the *preceding* hour, so its true centre is
    30 min earlier — interpolate it back onto the hour so every column shares
    one timestamp."""
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").astype(float)
    rad = df["shortwave_radiation"].copy()
    rad.index = rad.index - pd.Timedelta(minutes=30)
    rad = rad.reindex(rad.index.union(df.index)).interpolate(method="time", limit_area="inside")
    out = pd.DataFrame({
        "nwp_ghi": rad.reindex(df.index),
        "cloud_cover": df["cloud_cover"],
        "temp_c": df["temperature_2m"],
        "rh": df["relative_humidity_2m"],
    })
    out.index.name = "ts_utc"
    return out


def fetch(start: str, end: str) -> pd.DataFrame:
    r = get(config.OPEN_METEO_HISTORICAL_FORECAST_URL, params={
        "latitude": config.LATITUDE, "longitude": config.LONGITUDE,
        "start_date": start, "end_date": end,
        "hourly": HOURLY_VARS, "timezone": "GMT",
    })
    return parse_hourly(r.json()["hourly"]).dropna(how="all")


if __name__ == "__main__":
    start, end = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else (config.TRAIN_START, config.TRAIN_END)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    df = fetch(start, end)
    df.round(2).to_csv(WEATHER_CSV)
    print(f"Open-Meteo: {len(df)} hourly rows {df.index.min()} -> {df.index.max()} -> {WEATHER_CSV}")
