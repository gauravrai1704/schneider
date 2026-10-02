from datetime import datetime, timedelta

import pytest

from app import forecast, live_data
from app.config import IST, PUMP_RATED_W, SAFE_MIN_LEVEL_PCT, TANK_CAPACITY_LITRES
from app.municipal import in_window, minutes_until_next_window, next_window_start
from app.scheduler import Scheduler, TankSnapshot
from app.soc import feeder_soc, fillable_litres, minutes_until_safe_min

NOON = datetime(2026, 3, 1, 12, 0, tzinfo=IST)
SUNNY_W = 500.0


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Deterministic forecasts: no live weather, clear-sky persistence only."""
    monkeypatch.setattr(live_data.weather, "data", None)
    monkeypatch.setattr(live_data.weather, "fetched_at", -1.0)
    monkeypatch.setattr("app.config.OFFLINE", True)
    forecast._k_curve.cache_clear()


def tanks(n, level=50.0, sump=80.0):
    return [TankSnapshot(f"t{i}", level, sump) for i in range(n)]


def on_ids(decisions):
    return {d.building_id for d in decisions if d.action == "ON"}


# ---------------------------------------------------------------- stagger
def test_one_start_per_live_tick_and_running_pumps_stay_on():
    s = Scheduler()
    ts = tanks(4)
    first = s.decide(ts, SUNNY_W, NOON)
    assert len(on_ids(first)) == 1
    held = [d for d in first if d.action == "OFF"]
    assert all("staggered" in d.reason for d in held)

    # 5 s later telemetry still says every pump is off (lag) — the started one must stay ON
    second = s.decide(ts, SUNNY_W, NOON + timedelta(seconds=5))
    assert on_ids(first) <= on_ids(second)
    assert len(on_ids(second)) == 2


def test_no_start_within_stagger_gap():
    s = Scheduler()
    s.decide(tanks(3), SUNNY_W, NOON)
    again = s.decide(tanks(3), SUNNY_W, NOON + timedelta(seconds=1))
    assert len(on_ids(again)) == 1   # only the pump started a second ago


def test_long_simulator_step_allows_many_starts():
    s = Scheduler()
    s.decide(tanks(50), SUNNY_W, NOON)
    later = s.decide(tanks(50), SUNNY_W, NOON + timedelta(minutes=5))
    assert len(on_ids(later)) == 50


def test_emptiest_tank_starts_first():
    s = Scheduler()
    ts = [TankSnapshot("full", 80, 80), TankSnapshot("empty", 20, 80), TankSnapshot("mid", 50, 80)]
    assert on_ids(s.decide(ts, SUNNY_W, NOON)) == {"empty"}


# ---------------------------------------------------------------- safety
def test_safety_refill_has_hysteresis_and_ignores_solar():
    s = Scheduler()
    night = datetime(2026, 3, 1, 23, 0, tzinfo=IST)
    d = s.decide([TankSnapshot("a", SAFE_MIN_LEVEL_PCT - 5, 80)], 0.0, night)[0]
    assert d.action == "ON" and "safe minimum" in d.reason
    d = s.decide([TankSnapshot("a", SAFE_MIN_LEVEL_PCT + 5, 80, True)], 0.0, night + timedelta(seconds=5))[0]
    assert d.action == "ON"     # still inside the refill band
    d = s.decide([TankSnapshot("a", SAFE_MIN_LEVEL_PCT + 15, 80, True)], 0.0, night + timedelta(seconds=10))[0]
    assert d.action == "OFF"


def test_dry_run_beats_low_tank():
    d = Scheduler().decide([TankSnapshot("a", 5.0, 3.0)], SUNNY_W, NOON)[0]
    assert d.action == "OFF" and "dry-run" in d.reason


def test_overflow_stops_pump():
    d = Scheduler().decide([TankSnapshot("a", 97.0, 80.0, True)], SUNNY_W, NOON)[0]
    assert d.action == "OFF" and "overflow" in d.reason


def test_pause_overrides_and_clears_commands():
    s = Scheduler()
    s.decide(tanks(2), SUNNY_W, NOON)
    s.set_pause(True)
    assert on_ids(s.decide(tanks(2), SUNNY_W, NOON + timedelta(seconds=5))) == set()
    assert s.commanded_on == set()


# ---------------------------------------------------------------- municipal
def test_supply_windows():
    assert in_window(datetime(2026, 3, 1, 6, 30, tzinfo=IST))
    assert not in_window(datetime(2026, 3, 1, 12, 0, tzinfo=IST))
    assert next_window_start(datetime(2026, 3, 1, 12, 0, tzinfo=IST)) == datetime(2026, 3, 1, 18, 0, tzinfo=IST)
    assert next_window_start(datetime(2026, 3, 1, 21, 0, tzinfo=IST)) == datetime(2026, 3, 2, 5, 0, tzinfo=IST)
    assert minutes_until_next_window(datetime(2026, 3, 1, 17, 15, tzinfo=IST)) == 45


def test_full_sump_is_emptied_before_supply_window():
    before = datetime(2026, 3, 1, 17, 15, tzinfo=IST)
    d = Scheduler().decide([TankSnapshot("a", 80.0, 90.0)], 0.0, before)[0]
    assert d.action == "ON" and "municipal supply at 18:00" in d.reason
    # far from any window, the same tank just holds
    d = Scheduler().decide([TankSnapshot("a", 80.0, 90.0)], 0.0, datetime(2026, 3, 1, 23, 0, tzinfo=IST))[0]
    assert d.action == "OFF"


# ---------------------------------------------------------------- SoC
def test_fillable_is_limited_by_sump_water():
    assert fillable_litres(40, None) == pytest.approx(0.6 * TANK_CAPACITY_LITRES)
    assert fillable_litres(40, 11) < fillable_litres(40, 90)   # nearly-dry sump can't fill the tank
    assert fillable_litres(40, 10) == 0


def test_feeder_soc_numbers():
    now = datetime(2026, 3, 1, 7, 30, tzinfo=IST)   # morning peak demand
    rows = [
        {"building_id": "a", "level_pct": 50, "sump_level_pct": 90, "pump_on": True, "pump_w": PUMP_RATED_W},
        {"building_id": "b", "level_pct": 20, "sump_level_pct": 90, "pump_on": False, "pump_w": 0},
    ]
    out = feeder_soc(rows, now)
    assert out["tanks_reporting"] == 2 and out["pumps_running"] == 1
    assert out["sheddable_w"] == PUMP_RATED_W
    # the emptier tank limits how long a pause can last
    assert out["pause_minutes_available"] == round(minutes_until_safe_min("b", 20, now))
    assert 0 < out["pause_minutes_available"] < minutes_until_safe_min("a", 50, now)


def test_no_grid_pumping_at_night_just_because_solar_is_zero():
    night = datetime(2026, 3, 1, 21, 0, tzinfo=IST)
    d = Scheduler().decide([TankSnapshot("a", 40.0, 50.0)], 0.0, night)[0]
    assert d.action == "OFF"


def test_surplus_ending_soon_gets_start_priority():
    late_afternoon = datetime(2026, 3, 1, 17, 0, tzinfo=IST)   # clear-sky forecast drops below threshold by 18:00
    s = Scheduler()
    d = s.decide([TankSnapshot("a", 50.0, 50.0)], SUNNY_W, late_afternoon)[0]
    assert d.action == "ON" and "predicted dip" in d.reason


def test_during_evening_window_only_a_nearly_full_sump_pumps():
    during = datetime(2026, 3, 1, 18, 30, tzinfo=IST)   # supply window, also the evening grid peak
    d = Scheduler().decide([TankSnapshot("a", 60.0, 80.0)], 0.0, during)[0]
    assert d.action == "OFF"
    d = Scheduler().decide([TankSnapshot("a", 60.0, 95.0)], 0.0, during)[0]
    assert d.action == "ON" and "supply on now" in d.reason


def test_sump_transfer_has_hysteresis():
    during = datetime(2026, 3, 1, 18, 30, tzinfo=IST)
    s = Scheduler()
    assert s.decide([TankSnapshot("a", 60.0, 92.0)], 0.0, during)[0].action == "ON"
    # sump dropped just below the 90% trigger — keep transferring, don't flap
    assert s.decide([TankSnapshot("a", 61.0, 88.0, True)], 0.0, during + timedelta(seconds=5))[0].action == "ON"
    assert s.decide([TankSnapshot("a", 63.0, 78.0, True)], 0.0, during + timedelta(seconds=10))[0].action == "OFF"
