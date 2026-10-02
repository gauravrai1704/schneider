"""Shared helpers for the data download scripts."""
from __future__ import annotations
import os
import time

import requests

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BACKEND_DIR, "data", "raw")
PROCESSED_DIR = os.path.join(BACKEND_DIR, "data", "processed")

SOLAR_CSV = os.path.join(PROCESSED_DIR, "solar_nasa_power.csv")
WEATHER_CSV = os.path.join(PROCESSED_DIR, "weather_openmeteo.csv")
LOAD_CSV = os.path.join(PROCESSED_DIR, "load_delhi_sldc.csv")

USER_AGENT = "VirtualTankBattery-hackathon/0.1 (research prototype)"


def get(url: str, params: dict | None = None, timeout: int = 90, retries: int = 3) -> requests.Response:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")
