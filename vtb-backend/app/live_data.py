"""
Live external data feeds:
  - weather: Open-Meteo forecast for the configured location (irradiance,
    cloud cover, temperature, humidity), refreshed every 15 min
  - grid:    Delhi SLDC real-time load page (today, yesterday, a week ago),
    refreshed every 5 min

Callers never block on the network: get() returns whatever is cached and,
if stale, kicks off a refresh on a background thread. The last good response
is persisted to data/cache/ so a restart without internet still has data.
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta

import pandas as pd

from app import config
from app.clock import now_ist

log = logging.getLogger("vtb.live")

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")


class _Feed:
    def __init__(self, name: str, refresh_sec: int):
        self.name = name
        self.refresh_sec = refresh_sec
        self.data = None
        self.fetched_at: float = 0.0
        self.source = "none"            # "live" | "disk-cache" | "none"
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._refreshing = False
        self._load_disk()

    # subclasses implement these
    def _fetch_raw(self):
        raise NotImplementedError

    def _parse(self, raw):
        raise NotImplementedError

    @property
    def _cache_path(self):
        return os.path.join(CACHE_DIR, f"{self.name}.json")

    def _load_disk(self):
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                blob = json.load(f)
            self.data = self._parse(blob["raw"])
            self.fetched_at = blob["fetched_at"]
            self.source = "disk-cache"
        except (OSError, ValueError, KeyError):
            pass

    def _refresh(self):
        try:
            raw = self._fetch_raw()
            data = self._parse(raw)
            self.data, self.fetched_at, self.source, self.last_error = data, time.time(), "live", None
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": self.fetched_at, "raw": raw}, f)
        except Exception as e:
            self.last_error = f"{e.__class__.__name__}: {e}"
            log.warning("%s refresh failed: %s", self.name, self.last_error)
        finally:
            self._refreshing = False

    def stale(self) -> bool:
        return time.time() - self.fetched_at > self.refresh_sec

    def get(self):
        if self.stale() and not config.OFFLINE:
            with self._lock:
                if not self._refreshing:
                    self._refreshing = True
                    threading.Thread(target=self._refresh, name=f"refresh-{self.name}", daemon=True).start()
        return self.data

    def refresh_now(self):
        """Blocking refresh — for scripts/tests, never call from the event loop."""
        self._refreshing = True
        self._refresh()
        return self.data

    def status(self) -> dict:
        age = time.time() - self.fetched_at if self.fetched_at else None
        # "fresh" goes by age, not origin: data loaded from disk at start-up is still current
        return {"source": self.source, "age_sec": round(age) if age is not None else None,
                "fresh": age is not None and age < 2 * self.refresh_sec, "last_error": self.last_error}


class WeatherFeed(_Feed):
    """Hourly Open-Meteo forecast, yesterday through tomorrow, UTC-indexed."""

    def __init__(self):
        super().__init__("open_meteo_forecast", config.WEATHER_REFRESH_SEC)

    def _fetch_raw(self):
        from etl.common import get
        from etl.fetch_weather import HOURLY_VARS
        r = get(config.OPEN_METEO_FORECAST_URL, params={
            "latitude": config.LATITUDE, "longitude": config.LONGITUDE,
            "hourly": HOURLY_VARS, "past_days": 1, "forecast_days": 2, "timezone": "GMT",
        }, timeout=20)
        return r.json()["hourly"]

    def _parse(self, raw):
        from etl.fetch_weather import parse_hourly
        return parse_hourly(raw)

    def at(self, times_utc: pd.DatetimeIndex) -> pd.DataFrame | None:
        """Weather interpolated to arbitrary instants; None if no data at all."""
        df = self.get()
        if df is None or df.empty:
            return None
        out = df.reindex(df.index.union(times_utc)).interpolate(method="time", limit_area="inside")
        return out.reindex(times_utc)


class GridFeed(_Feed):
    """Delhi SLDC load for the configured DISCOM, 15-min means, naive-IST index.
    Fetches today + yesterday + 7 days ago (lag features for the load model)."""

    def __init__(self):
        super().__init__("delhi_sldc_load", config.GRID_REFRESH_SEC)
        self._day_cache: dict[str, list] = {}  # past days never change; fetch once

    def _days(self) -> list[date]:
        today = now_ist().date()
        return [today - timedelta(days=8), today - timedelta(days=7), today - timedelta(days=1), today]

    def _fetch_raw(self):
        from etl.fetch_load import fetch_day_html, parse_day
        today = now_ist().date()
        rows = []
        for d in self._days():
            key = d.isoformat()
            if d == today or key not in self._day_cache:
                df = parse_day(fetch_day_html(d), d)
                recs = [[ts.isoformat(), v] for ts, v in df[config.LOAD_DISCOM].dropna().items()]
                if d != today and len(recs) > 200:
                    self._day_cache[key] = recs
            else:
                recs = self._day_cache[key]
            rows.extend(recs)
        return rows

    def _parse(self, raw):
        s = pd.Series({pd.Timestamp(ts): v for ts, v in raw}, dtype=float).sort_index()
        s = s[s > 0]
        return s.resample("15min").mean().dropna()

    def value_at(self, ts_ist: datetime, tolerance_min: int = 20) -> float | None:
        s = self.get()
        if s is None or s.empty:
            return None
        ts = pd.Timestamp(ts_ist.replace(tzinfo=None))
        i = s.index.get_indexer([ts], method="nearest")[0]
        if i < 0 or abs((s.index[i] - ts).total_seconds()) > tolerance_min * 60:
            return None
        return float(s.iloc[i])

    def latest(self, max_age_min: int = 60) -> tuple[datetime, float] | None:
        s = self.get()
        if s is None or s.empty:
            return None
        ts = s.index[-1].to_pydatetime().replace(tzinfo=config.IST)
        if now_ist() - ts > timedelta(minutes=max_age_min):
            return None
        return ts, float(s.iloc[-1])


weather = WeatherFeed()
grid = GridFeed()


def status() -> dict:
    return {"offline_mode": config.OFFLINE, "weather": weather.status(), "grid": grid.status()}
