from datetime import datetime

import pytest

from app import forecast, live_data
from app.config import IST
from app.scheduler import HEADROOM_REASON, Scheduler, TankSnapshot
from app.sim_inputs import build_inputs
from app.simulator import run_simulation

DAY = datetime(2026, 10, 2, tzinfo=IST)
NOON = datetime(2026, 3, 1, 12, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(live_data.weather, "data", None)
    monkeypatch.setattr(live_data.weather, "fetched_at", -1.0)
    monkeypatch.setattr("app.config.OFFLINE", True)
    forecast._k_curve.cache_clear()


@pytest.fixture(scope="module")
def sims():
    return {cloudy: run_simulation(60, DAY, cloudy) for cloudy in (False, True)}


def test_inputs_come_from_real_data():
    normal, cloudy = build_inputs(DAY, False), build_inputs(DAY, True)
    assert "NASA POWER" in normal.solar_source and "Delhi SLDC" in normal.load_source
    assert cloudy.ghi.sum() < normal.ghi.sum()
    assert normal.load_shape.max() == pytest.approx(1.0, abs=0.02)
    assert len(normal.times) == 288


@pytest.mark.parametrize("cloudy", [False, True])
def test_vtb_moves_pumping_to_solar_without_new_peak_or_dry_tanks(sims, cloudy):
    r = sims[cloudy]
    base, rules = r["metrics"]["baseline"], r["metrics"]["rules"]
    assert rules["green_share_pct"] > base["green_share_pct"] + 30
    assert rules["evening_peak_pump_kwh"] < 0.1 * base["evening_peak_pump_kwh"] + 0.1
    assert rules["net_peak_kw"] <= base["net_peak_kw"] + 0.5       # never creates a new peak
    assert rules["pct_time_below_safe_min"] == 0 and rules["unmet_water_litres"] == 0
    assert r["kwh_shifted"] > 0


def test_lp_benchmark_solves_and_never_beats_physics(sims):
    r = sims[False]
    opt = r["metrics"]["optimal"]
    assert r["optimizer_status"] == "Optimal"
    assert opt["net_peak_kw"] <= r["metrics"]["baseline"]["net_peak_kw"] + 0.5
    assert opt["evening_peak_pump_kwh"] == 0
    assert all(p["optimal_w"] >= 0 for p in r["curve"])


def test_simulation_is_deterministic():
    a = run_simulation(40, DAY, False, with_optimal=False)
    from app.simulator import _simulate
    _simulate.cache_clear()
    b = run_simulation(40, DAY, False, with_optimal=False)
    assert a["metrics"] == b["metrics"]


def test_headroom_cap_limits_running_pumps_but_not_safety():
    s = Scheduler()
    tanks = [TankSnapshot(f"t{i}", 50.0, 80.0, True) for i in range(5)] + [TankSnapshot("low", 5.0, 80.0, True)]
    out = s.decide(tanks, 500.0, NOON, max_running=2)
    on = [d for d in out if d.action == "ON"]
    assert {d.building_id for d in on} >= {"low"}            # safety refill exempt
    assert len(on) == 2                                      # the refill still uses one of the 2 slots
    assert any(d.reason == HEADROOM_REASON for d in out)


def test_zero_headroom_holds_everything_except_safety():
    out = Scheduler().decide([TankSnapshot("a", 50.0, 80.0), TankSnapshot("b", 5.0, 80.0)], 500.0, NOON, max_running=0)
    assert {d.building_id: d.action for d in out} == {"a": "OFF", "b": "ON"}


def test_valley_ceiling_fills_lowest_steps_first_and_never_exceeds_peak():
    import numpy as np
    from app.headroom import SAFETY_MARGIN, pumps_allowed, valley_ceiling
    net = np.array([300.0, 200.0, 150.0, 200.0, 300.0])
    green = np.array([False, True, True, True, False])
    ceiling = valley_ceiling(net, green, pump_w=10.0, pump_hours_needed=4.0, step_h=1.0)
    assert 150 < ceiling < 300
    room = sum(pumps_allowed(n, ceiling, 10.0) for n in net[green])
    assert room >= 4.0 * SAFETY_MARGIN - 1                 # enough room, give or take rounding
    assert valley_ceiling(net, green, 10.0, 1e6, 1.0) == 300.0   # impossible demand -> capped at the peak
