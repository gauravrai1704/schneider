import os
import time
from datetime import datetime, timedelta

import pytest

os.environ["VTB_OFFLINE"] = "1"
from fastapi.testclient import TestClient  # noqa: E402

from app import config, state  # noqa: E402
from app.alerts import LeakDetector, resident_alerts  # noqa: E402
from app.config import IST  # noqa: E402
from app.impact import REAL_SCALE, ImpactTracker  # noqa: E402
from app.main import app  # noqa: E402
from app.tariff import factor, period, rate_inr_per_kwh  # noqa: E402

NIGHT = datetime(2026, 3, 1, 2, 0, tzinfo=IST)


# ---------------------------------------------------------------- tariff
def test_tod_periods_follow_the_rules():
    assert period(datetime(2026, 3, 1, 12, tzinfo=IST)) == "solar"
    assert period(datetime(2026, 3, 1, 19, tzinfo=IST)) == "peak"
    assert period(NIGHT) == "normal"
    assert factor(datetime(2026, 3, 1, 12, tzinfo=IST)) <= 0.80          # >= 20% off in solar hours
    assert factor(datetime(2026, 3, 1, 19, tzinfo=IST)) >= 1.10          # >= 1.10x at peak (domestic)
    assert rate_inr_per_kwh(NIGHT) == config.TARIFF_NORMAL_INR_PER_KWH


# ---------------------------------------------------------------- leaks
def _feed(det, levels, pump_on=False, step=10.0, start=NIGHT):
    for i, lvl in enumerate(levels):
        det.observe("tank-01", lvl, pump_on, start + timedelta(seconds=i * step), mono=i * step)


def test_fast_drain_with_idle_pump_is_a_leak(monkeypatch):
    monkeypatch.setattr(config, "TELEMETRY_TIME_SCALE", 1.0)
    det = LeakDetector()
    _feed(det, [80 - i * 0.2 for i in range(70)])          # ~14% in ~11 min at 2 am = ~770 L/h
    leak = det.check("tank-01")
    assert leak and leak["observed_lph"] > leak["expected_lph"] * 3


def test_normal_use_is_not_a_leak(monkeypatch):
    monkeypatch.setattr(config, "TELEMETRY_TIME_SCALE", 1.0)
    det = LeakDetector()
    _feed(det, [80 - i * 0.0005 for i in range(70)])
    assert det.check("tank-01") is None


def test_no_leak_verdict_while_pump_runs_or_history_short(monkeypatch):
    monkeypatch.setattr(config, "TELEMETRY_TIME_SCALE", 1.0)
    det = LeakDetector()
    _feed(det, [80 - i * 0.2 for i in range(70)], pump_on=True)
    assert det.check("tank-01") is None
    short = LeakDetector()
    _feed(short, [80 - i * 0.5 for i in range(5)])
    assert short.check("tank-01") is None


def test_resident_alert_texts():
    supply = datetime(2026, 3, 1, 5, 0, tzinfo=IST)
    alerts = resident_alerts({"level_pct": 10, "sump_level_pct": 5}, {"observed_lph": 400, "expected_lph": 20}, True, supply)
    codes = {a["code"] for a in alerts}
    assert codes == {"low", "leak", "dry_run", "paused"}
    assert all(a["tone"] in {"good", "warning", "critical"} for a in alerts)


# ---------------------------------------------------------------- impact
def test_impact_tracker_counts_energy_green_share_and_savings():
    tr = ImpactTracker()
    tr.day = datetime(2026, 3, 1).date()      # skip the DB load for a fresh day
    noon = datetime(2026, 3, 1, 12, 0, tzinfo=IST)
    tanks = [{"building_id": "a", "pump_on": True, "pump_w": 40.0}, {"building_id": "b", "pump_on": False, "pump_w": 0}]
    tr.tick(noon, tanks, solar_w=400.0, feeder_load_w=600.0, paused=False, dt_s=3600)
    s = tr.summary()
    assert s["wh_pumped"] == pytest.approx(40.0)
    assert s["green_share_pct"] == 100.0
    # 40 Wh demo -> real pump kWh at normal rate, 20% saved in solar hours
    expected_saving = 40 * REAL_SCALE / 1000 * config.TARIFF_NORMAL_INR_PER_KWH * (1 - config.TARIFF_SOLAR_FACTOR)
    assert s["tod_saving_inr"] == pytest.approx(expected_saving, abs=0.01)
    tr.record_pause(noon, 120.0)
    assert tr.summary()["pause_events"] == 1 and tr.summary()["max_shed_w"] == 120.0


# ---------------------------------------------------------------- API
def test_phase5_endpoints_live():
    state.last_sent.clear()
    state.scheduler.commanded_on.clear()
    with TestClient(app) as client:
        assert client.get("/", follow_redirects=False).headers["location"] == "/docs"
        time.sleep(6)
        impact = client.get("/impact").json()
        assert {"wh_pumped", "green_share_pct", "tod_saving_inr", "pause_events", "tariff"} <= impact.keys()

        r = client.get("/resident/tank-01").json()
        assert {"level_pct", "litres", "pump", "next_pump", "next_supply", "alerts", "savings"} <= r.keys()
        assert r["next_pump"]["why"]
        assert client.get("/resident/nope").status_code == 404

        assert client.get("/demo").json()["mock_running"] is True
        assert client.post("/demo/cloud", json={"active": True}).json() == {"cloud": True}
        assert client.get("/demo").json()["cloud"] is True
        client.post("/demo/cloud", json={"active": False})
        assert client.post("/demo/leak", json={"building_id": "tank-03", "active": True}).status_code == 200
        assert client.get("/demo").json()["leaks"] == ["tank-03"]
        client.post("/demo/leak", json={"building_id": "tank-03", "active": False})
        assert client.post("/demo/leak", json={"building_id": "nope", "active": True}).status_code == 404

        assert isinstance(client.get("/loadcurve").json(), list)
        assert isinstance(client.get("/commands").json(), list)


def test_pause_survives_restart():
    with TestClient(app) as client:
        client.post("/pause", json={"active": True})
        time.sleep(0.3)
        assert client.get("/pause").json() == {"active": True}
    state.scheduler.set_pause(False)           # simulate a fresh process
    with TestClient(app) as client:
        assert client.get("/pause").json() == {"active": True}
        client.post("/pause", json={"active": False})
        time.sleep(0.3)
        assert client.get("/pause").json() == {"active": False}


def test_pause_still_refills_a_tank_below_safe_minimum():
    from app.scheduler import Scheduler, TankSnapshot
    s = Scheduler()
    s.set_pause(True)
    out = {d.building_id: d for d in s.decide(
        [TankSnapshot("ok", 50, 80), TankSnapshot("low", 10, 80), TankSnapshot("dry_sump", 10, 5)], 500.0, NOON_)}
    assert out["ok"].action == "OFF" and out["dry_sump"].action == "OFF"
    assert out["low"].action == "ON" and "despite the DISCOM pause" in out["low"].reason


NOON_ = datetime(2026, 3, 1, 12, 0, tzinfo=IST)
