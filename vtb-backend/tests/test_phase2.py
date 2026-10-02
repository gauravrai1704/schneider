from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app import forecast, live_data
from app.config import IST
from app.features import LOAD_FEATURES, SOLAR_FEATURES, clearness, load_frame, solar_frame
from app.solar_geometry import clear_sky_ghi, clear_sky_ghi_series
from etl.fetch_load import parse_day
from etl.fetch_weather import parse_hourly

SLDC_SNIPPET = """<html><body><table id="ContentPlaceHolder3_DGGridAv">
<tr><td>TIMESLOT</td><td>DELHI</td><td>BRPL</td><td>BYPL</td></tr>
<tr><td>00:00</td><td>6261.330</td><td>2728.320</td><td>1465.000</td></tr>
<tr><td>00:05</td><td>6222.180</td><td>2706.870</td><td>1461.300</td></tr>
</table></body></html>"""


def test_sldc_parser():
    df = parse_day(SLDC_SNIPPET, date(2025, 9, 15))
    assert list(df.columns) == ["DELHI", "BRPL", "BYPL"]
    assert df.index[1] == pd.Timestamp("2025-09-15 00:05")
    assert df["BYPL"].iloc[0] == pytest.approx(1465.0)


def test_open_meteo_radiation_is_recentred():
    # radiation is a preceding-hour mean: 0 for 05-06, 100 for 06-07 -> ~50 at 06:00
    parsed = parse_hourly({
        "time": ["2026-01-01T05:00", "2026-01-01T06:00", "2026-01-01T07:00"],
        "shortwave_radiation": [0, 0, 100], "cloud_cover": [10, 20, 30],
        "temperature_2m": [10, 11, 12], "relative_humidity_2m": [50, 50, 50],
    })
    assert parsed.loc["2026-01-01 06:00+00:00", "nwp_ghi"] == pytest.approx(50)
    assert parsed.loc["2026-01-01 06:00+00:00", "cloud_cover"] == 20


def test_clear_sky_follows_delhi_sun():
    june_noon = clear_sky_ghi(datetime(2026, 6, 21, 12, 20, tzinfo=IST))
    dec_noon = clear_sky_ghi(datetime(2026, 12, 21, 12, 20, tzinfo=IST))
    assert 950 < june_noon < 1100 and 550 < dec_noon < 700
    assert clear_sky_ghi(datetime(2026, 6, 21, 4, 0, tzinfo=IST)) == 0
    assert clear_sky_ghi(datetime(2026, 12, 21, 18, 0, tzinfo=IST)) == 0
    # scalar and vectorised versions agree
    ts = pd.DatetimeIndex([pd.Timestamp("2026-03-01 06:30", tz="UTC")])
    assert clear_sky_ghi_series(ts)[0] == pytest.approx(clear_sky_ghi(ts[0].to_pydatetime()), rel=1e-6)


def test_clearness_masks_night():
    k = clearness([0, 500, 900], [10, 1000, 600])
    assert np.isnan(k[0]) and k[1] == 0.5 and k[2] == 1.3  # clipped


def test_feature_frames_have_model_columns():
    t = pd.DatetimeIndex([pd.Timestamp("2026-03-01 10:00", tz=IST)] * 2)
    s = solar_frame([60, 120], t, [800, 850], [700, 600], [20, 40], 0.9, 0.85, np.nan)
    assert list(s.columns) == SOLAR_FEATURES and s.shape == (2, len(SOLAR_FEATURES))
    ld = load_frame([15, 30], t, [25, 26], [40, 41], 1000.0, np.nan, 990.0)
    assert list(ld.columns) == LOAD_FEATURES
    assert ld["is_holiday"].iloc[0] == 0


def test_republic_day_is_holiday():
    t = pd.DatetimeIndex([pd.Timestamp("2026-01-26 10:00", tz=IST)])
    assert load_frame([15], t, 20, 40, 1, 1, 1)["is_holiday"].iloc[0] == 1


@pytest.fixture
def no_live_data(monkeypatch):
    monkeypatch.setattr(live_data.weather, "data", None)
    monkeypatch.setattr(live_data.weather, "fetched_at", -1.0)
    monkeypatch.setattr(live_data.grid, "data", None)
    monkeypatch.setattr("app.config.OFFLINE", True)
    forecast._k_curve.cache_clear()


def test_solar_falls_back_to_persistence_without_weather(no_live_data):
    noon = datetime(2026, 3, 1, 12, 0, tzinfo=IST)
    out = forecast.solar_forecast(noon, [0, 60], 0.5)
    assert all(p["source"] == "clear-sky-persistence" for p in out)
    assert out[0]["solar_w"] == pytest.approx(0.5 * forecast.clear_sky_w(noon), abs=0.1)


def test_load_works_without_live_feeds(no_live_data):
    out = forecast.load_forecast(datetime(2026, 3, 1, 20, 0, tzinfo=IST), [0, 60, 360])
    expected = "ml-calendar-weather" if forecast.USING_ML_LOAD else "heuristic"
    assert all(p["source"] == expected and p["feeder_load_w"] > 0 for p in out)


@pytest.mark.skipif(not forecast.USING_ML_SOLAR, reason="models not trained")
def test_covered_panel_forecasts_lower_solar(monkeypatch):
    t = datetime(2026, 3, 1, 11, 0, tzinfo=IST)
    hours = pd.date_range("2026-03-01 00:00", periods=24, freq="1h", tz="UTC")
    cs = clear_sky_ghi_series(hours)
    wx = pd.DataFrame({"nwp_ghi": cs * 0.9, "cloud_cover": 10.0, "temp_c": 25.0, "rh": 40.0}, index=hours)
    monkeypatch.setattr(live_data.weather, "data", wx)
    monkeypatch.setattr(live_data.weather, "fetched_at", 1e12)  # fresh: no refresh thread
    forecast._k_curve.cache_clear()
    sunny = forecast.solar_forecast(t, [30, 60], 1.0)
    covered = forecast.solar_forecast(t, [30, 60], 0.2)
    assert covered[0]["source"] == "ml+open-meteo+panel"
    assert all(c["solar_w"] < s["solar_w"] for c, s in zip(covered, sunny))
    assert forecast.is_predicted_dip(t, 30, 200, 0.1)
