from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app import config, live_data, state
from app.clock import now_ist
from app.config import IST
from app.scheduler import Decision

# ---------------------------------------------------------------- live feeds: cache + failure handling
HOURLY = {
    "time": ["2026-03-01T05:00", "2026-03-01T06:00", "2026-03-01T07:00", "2026-03-01T08:00"],
    "shortwave_radiation": [0, 100, 300, 500],
    "cloud_cover": [10, 20, 30, 40],
    "temperature_2m": [20, 22, 24, 26],
    "relative_humidity_2m": [50, 50, 50, 50],
}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(live_data, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "OFFLINE", False)
    return tmp_path


def test_weather_feed_refresh_interpolate_and_disk_cache(cache_dir, monkeypatch):
    feed = live_data.WeatherFeed()
    monkeypatch.setattr(feed, "_fetch_raw", lambda: HOURLY)
    feed.refresh_now()
    assert feed.status()["source"] == "live"
    at = feed.at(pd.DatetimeIndex([pd.Timestamp("2026-03-01 06:30", tz="UTC")]))
    assert at["temp_c"].iloc[0] == pytest.approx(23.0)

    # A fresh process with no network gets the last good response from disk
    restarted = live_data.WeatherFeed()
    assert restarted.status()["source"] == "disk-cache"
    assert restarted.data is not None and len(restarted.data) == 4


def test_feed_failure_keeps_last_good_data(cache_dir, monkeypatch):
    feed = live_data.WeatherFeed()
    monkeypatch.setattr(feed, "_fetch_raw", lambda: HOURLY)
    feed.refresh_now()

    def boom():
        raise ConnectionError("venue wifi down")
    monkeypatch.setattr(feed, "_fetch_raw", boom)
    feed.refresh_now()
    assert feed.data is not None and "venue wifi down" in feed.status()["last_error"]


def test_grid_feed_latest_respects_freshness(cache_dir, monkeypatch):
    now = now_ist().replace(second=0, microsecond=0, tzinfo=None)
    rows = [[(now - timedelta(minutes=m)).isoformat(), 1000.0 + m] for m in range(5, 120, 5)]
    feed = live_data.GridFeed()
    monkeypatch.setattr(feed, "_fetch_raw", lambda: rows)
    feed.refresh_now()
    ts, mw = feed.latest()
    assert now_ist() - ts < timedelta(minutes=30) and mw > 1000
    assert feed.value_at(now_ist() - timedelta(minutes=60)) is not None
    assert feed.value_at(now_ist() - timedelta(days=3)) is None       # outside tolerance

    stale = [[(now - timedelta(hours=5, minutes=m)).isoformat(), 900.0] for m in range(0, 60, 5)]
    monkeypatch.setattr(feed, "_fetch_raw", lambda: stale)
    feed.refresh_now()
    assert feed.latest() is None          # too old to use as "load now"


# ---------------------------------------------------------------- training data: no look-ahead leakage
def test_load_training_features_never_peek_at_the_target():
    from app.train_forecast import build_load_set
    df, peak = build_load_set()
    assert peak > 0
    from etl.common import LOAD_CSV
    ld = pd.read_csv(LOAD_CSV, index_col="ts_ist", parse_dates=True)[config.LOAD_DISCOM]
    rows = df.dropna(subset=["load_yday", "load_now"]).sample(30, random_state=1)
    for _, r in rows.iterrows():
        issue = pd.Timestamp(r["issue_ts"]).tz_localize(None)
        tgt = issue + pd.Timedelta(minutes=int(r["horizon_min"]))
        assert r["load_now"] == pytest.approx(ld.get(issue, np.nan), nan_ok=True, abs=1)
        assert r["load_yday"] == pytest.approx(ld.get(tgt - pd.Timedelta(days=1), np.nan), nan_ok=True, abs=1)
        assert r["target_mw"] == pytest.approx(ld.get(tgt, np.nan), nan_ok=True, abs=1)


def test_solar_training_target_is_in_the_future():
    from app.train_forecast import build_solar_set
    df = build_solar_set()
    assert set(df["horizon_min"].unique()) == {60, 120, 180, 240, 300, 360}
    assert df["target_k"].between(0, 1.3).all()
    # The model is never asked about night-time targets
    assert (df["cs_tgt"] >= 50).all()


# ---------------------------------------------------------------- resident "next pump" logic
@pytest.fixture
def offline_forecast(monkeypatch):
    from app import forecast
    monkeypatch.setattr(live_data.weather, "data", None)
    monkeypatch.setattr(live_data.weather, "fetched_at", -1.0)
    monkeypatch.setattr(config, "OFFLINE", True)
    forecast._k_curve.cache_clear()


def test_next_pump_branches(offline_forecast, monkeypatch):
    from app.routes import _next_pump
    monkeypatch.setattr(state.scheduler, "discom_paused", False)
    morning = datetime(2026, 3, 1, 7, 0, tzinfo=IST)
    tank = {"level_pct": 50.0, "sump_level_pct": 80.0}

    assert _next_pump(tank, Decision("a", "ON", "x"), morning)["why"] == "Pumping now"
    assert _next_pump({"level_pct": 50.0, "sump_level_pct": 5.0}, None, morning)["why"].startswith("When municipal")
    assert _next_pump({"level_pct": 97.0, "sump_level_pct": 80.0}, None, morning)["at"] is None
    solar = _next_pump(tank, None, morning)
    assert solar["why"] == "Next solar window" and datetime.fromisoformat(solar["at"]) > morning
    night = _next_pump(tank, None, datetime(2026, 3, 1, 22, 0, tzinfo=IST))
    assert night["why"].startswith("Tomorrow") and datetime.fromisoformat(night["at"]).day == 2

    monkeypatch.setattr(state.scheduler, "discom_paused", True)
    assert _next_pump(tank, None, morning)["why"].startswith("When the grid operator")


def test_feed_loaded_from_disk_is_fresh_until_it_ages(cache_dir, monkeypatch):
    feed = live_data.WeatherFeed()
    monkeypatch.setattr(feed, "_fetch_raw", lambda: HOURLY)
    feed.refresh_now()
    restarted = live_data.WeatherFeed()
    assert restarted.status()["source"] == "disk-cache" and restarted.status()["fresh"] is True
    restarted.fetched_at -= 3 * restarted.refresh_sec
    assert restarted.status()["fresh"] is False


def test_demo_clock_starts_at_requested_time(monkeypatch):
    import importlib
    from app import clock
    monkeypatch.setenv("VTB_DEMO_TIME", "12:30")
    demo = importlib.reload(clock)
    try:
        t = demo.now_ist()
        assert (t.hour, t.minute) in {(12, 30), (12, 31)} and demo.DEMO_TIME == "12:30"
    finally:
        monkeypatch.delenv("VTB_DEMO_TIME")
        importlib.reload(clock)
    assert clock.DEMO_TIME is None
