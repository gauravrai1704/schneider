"""
Scrapes real 5-minute electricity demand for Delhi and each of its DISCOMs
from the Delhi State Load Despatch Centre (https://www.delhisldc.org —
public, one page per day). Parsed days are cached in data/raw/sldc/ so
re-runs only fetch what's missing.

    python -m etl.fetch_load [START END]

Output: data/processed/load_delhi_sldc.csv  (15-minute means, MW)
  ts_ist, DELHI, BRPL, BYPL, NDPL, NDMC, MES
"""
from __future__ import annotations
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
from bs4 import BeautifulSoup

from app import config
from etl.common import LOAD_CSV, PROCESSED_DIR, RAW_DIR, get

SLDC_RAW_DIR = os.path.join(RAW_DIR, "sldc")
TABLE_ID = "ContentPlaceHolder3_DGGridAv"


def parse_day(html: str, day: date) -> pd.DataFrame:
    """SLDC day page -> one row per 5-min slot (naive IST index). Shared with the live grid feed."""
    table = BeautifulSoup(html, "html.parser").find("table", id=TABLE_ID)
    if table is None:
        return pd.DataFrame()
    rows = [[c.get_text(strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
    header, body = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
    df = pd.DataFrame(body, columns=header)
    df["ts_ist"] = pd.to_datetime(day.isoformat() + " " + df.pop("TIMESLOT"), errors="coerce")
    df = df.dropna(subset=["ts_ist"]).set_index("ts_ist")
    return df.apply(pd.to_numeric, errors="coerce")


def fetch_day_html(day: date) -> str:
    return get(config.DELHI_SLDC_LOAD_URL, params={"mode": day.strftime("%d/%m/%Y")}, timeout=60).text


def _cached_day(day: date) -> pd.DataFrame:
    path = os.path.join(SLDC_RAW_DIR, f"{day.isoformat()}.csv")
    if os.path.exists(path):
        return pd.read_csv(path, index_col="ts_ist", parse_dates=True)
    try:
        df = parse_day(fetch_day_html(day), day)
    except Exception as e:  # one bad day must not kill a year-long scrape
        print(f"  {day}: failed ({e.__class__.__name__})")
        return pd.DataFrame()
    if len(df) > 200:  # only cache complete days (288 slots)
        df.to_csv(path)
    return df


def fetch(start: str, end: str, workers: int = 4) -> pd.DataFrame:
    os.makedirs(SLDC_RAW_DIR, exist_ok=True)
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    frames = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, df in enumerate(pool.map(_cached_day, days), 1):
            frames.append(df)
            if i % 30 == 0:
                print(f"  {i}/{len(days)} days")
    raw = pd.concat([f for f in frames if not f.empty]).sort_index()
    raw = raw[~raw.index.duplicated()]
    raw = raw.where(raw > 0)  # zero/negative readings are telemetry dropouts, not demand
    return raw.resample("15min").mean().dropna(how="all")


if __name__ == "__main__":
    start, end = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else (config.TRAIN_START, config.TRAIN_END)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    df = fetch(start, end)
    df.round(2).to_csv(LOAD_CSV)
    print(f"Delhi SLDC: {len(df)} 15-min rows {df.index.min()} -> {df.index.max()} -> {LOAD_CSV}")
    print(df.describe().round(0).to_string())
