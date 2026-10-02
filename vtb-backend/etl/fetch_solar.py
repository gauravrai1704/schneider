"""
Downloads hourly satellite-derived irradiance for Delhi from NASA POWER
(https://power.larc.nasa.gov — CERES/MERRA-2 based, public, no key).

    python -m etl.fetch_solar [START END]      # dates as YYYY-MM-DD

Output: data/processed/solar_nasa_power.csv
  ts_utc   centre of the hourly averaging interval (UTC)
  ghi      all-sky global horizontal irradiance, W/m²  (ALLSKY_SFC_SW_DWN)
  ghi_clr  NASA's clear-sky GHI for the same hour, W/m² (CLRSKY_SFC_SW_DWN)
"""
from __future__ import annotations
import os
import sys

import pandas as pd

from app import config
from etl.common import PROCESSED_DIR, SOLAR_CSV, get


def fetch(start: str, end: str) -> pd.DataFrame:
    r = get(config.NASA_POWER_HOURLY_URL, params={
        "parameters": "ALLSKY_SFC_SW_DWN,CLRSKY_SFC_SW_DWN",
        "community": "RE",
        "latitude": config.LATITUDE, "longitude": config.LONGITUDE,
        "start": start.replace("-", ""), "end": end.replace("-", ""),
        "format": "JSON", "time-standard": "UTC",
    }, timeout=180)
    params = r.json()["properties"]["parameter"]
    df = pd.DataFrame({
        "ghi": pd.Series(params["ALLSKY_SFC_SW_DWN"], dtype=float),
        "ghi_clr": pd.Series(params["CLRSKY_SFC_SW_DWN"], dtype=float),
    })
    df.index = pd.to_datetime(df.index, format="%Y%m%d%H", utc=True)
    df = df.where(df > -900).dropna()          # -999 = missing
    # NASA hourly values are averages over [HH:00, HH+1:00) -> label at the centre
    df.index = df.index + pd.Timedelta(minutes=30)
    df.index.name = "ts_utc"
    return df.clip(lower=0)


if __name__ == "__main__":
    start, end = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else (config.TRAIN_START, config.TRAIN_END)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    df = fetch(start, end)
    df.round(2).to_csv(SOLAR_CSV)
    print(f"NASA POWER: {len(df)} hourly rows {df.index.min()} -> {df.index.max()} -> {SOLAR_CSV}")
