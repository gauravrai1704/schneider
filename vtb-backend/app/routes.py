"""
Phase 5 endpoints: impact counters, today's load curve, resident view,
pause state and demo controls.
"""
from __future__ import annotations
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app import config, models, schemas, state
from app.alerts import resident_alerts
from app.bus import bus
from app.clock import now_ist
from app.database import get_db
from app.forecast import clear_sky_w, solar_forecast
from app.municipal import next_window_start
from app.tariff import describe as tariff_info
from app.water import daily_litres

router = APIRouter()


# ---------------------------------------------------------------- pause
@router.get("/pause")
def get_pause():
    return {"active": state.scheduler.discom_paused}


@router.post("/pause")
async def set_pause(req: schemas.PauseRequest):
    await bus.publish(config.TOPIC_DISCOM_PAUSE, {"active": req.active})
    return {"active": req.active}


# ---------------------------------------------------------------- impact + load curve
@router.get("/impact")
def impact():
    """Today's live impact on this feeder (IST day)."""
    return {**state.impact.summary(), "tariff": tariff_info()}


@router.get("/loadcurve")
def loadcurve(db: Session = Depends(get_db)):
    """Today's feeder in 5-minute averages: pump load, panel solar and feeder load (demo watts)."""
    start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    rows = db.query(models.LoadSample).filter(models.LoadSample.ts >= start).order_by(models.LoadSample.ts).all()
    return [{"ts": r.ts.isoformat(), "pump_w": round(r.pump_w, 1), "solar_w": round(r.solar_w, 1),
             "feeder_load_w": round(r.feeder_load_w, 1) if r.feeder_load_w is not None else None} for r in rows]


@router.get("/commands")
def commands(db: Session = Depends(get_db)):
    """Recent pump-command changes, newest first."""
    rows = db.query(models.PumpCommand).order_by(desc(models.PumpCommand.ts)).limit(200).all()
    return [{"building_id": r.building_id, "action": r.action, "reason": r.reason, "ts": r.ts} for r in rows]


# ---------------------------------------------------------------- resident
def _next_pump(tank: dict, decision, now: datetime) -> dict:
    paused = state.scheduler.discom_paused
    if decision and decision.action == "ON":
        return {"at": now.isoformat(), "why": "Pumping now"}
    if paused:
        return {"at": None, "why": "When the grid operator ends the pause"}
    if tank.get("sump_level_pct") is not None and tank["sump_level_pct"] <= config.SUMP_MIN_LEVEL_PCT:
        return {"at": next_window_start(now).isoformat(), "why": "When municipal supply refills the sump"}
    if tank["level_pct"] >= config.OVERFLOW_LEVEL_PCT:
        return {"at": None, "why": "Not needed — the tank is full"}
    from app.main import k_prev
    for p in solar_forecast(now, list(range(0, 361, 15)), state.live["clearness"], k_prev(now)):
        if p["solar_w"] >= config.SOLAR_SURPLUS_THRESHOLD_W:
            return {"at": (now + timedelta(minutes=p["horizon_min"])).isoformat(), "why": "Next solar window"}
    # No sun in the next 6 h: first clear-sky green moment tomorrow
    t = (now + timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
    while t.hour < 12 and clear_sky_w(t) < config.SOLAR_SURPLUS_THRESHOLD_W:
        t += timedelta(minutes=15)
    return {"at": t.isoformat(), "why": "Tomorrow, when solar returns"}


def _savings(building_id: str) -> dict:
    b = state.impact.per_building.get(building_id)
    real_daily_kwh = daily_litres(building_id) * config.ENERGY_PER_LITRE_WH / 1000
    share = (b["wh_green"] / b["wh"]) if b and b["wh"] > 0 else None
    out = {
        "today_wh": round(b["wh"], 2) if b else 0.0,
        "today_green_share_pct": round(100 * share, 1) if share is not None else None,
        "today_saving_inr": round(b["cost_flat"] - b["cost_tod"], 2) if b else 0.0,
        "real_pump_kwh_per_day": round(real_daily_kwh, 2),
        "monthly_saving_inr": None,
    }
    if share is not None:
        effective = share * config.TARIFF_SOLAR_FACTOR + (1 - share)
        out["monthly_saving_inr"] = round(real_daily_kwh * 30 * config.TARIFF_NORMAL_INR_PER_KWH * (1 - effective))
    return out


@router.get("/resident/{building_id}")
def resident(building_id: str):
    tank = state.latest_tanks.get(building_id)
    if tank is None:
        raise HTTPException(404, f"no telemetry for {building_id}")
    now = now_ist()
    decision = state.last_decisions.get(building_id)
    leak = state.leaks.check(building_id)
    supply = next_window_start(now)
    return {
        "building_id": building_id,
        "level_pct": tank["level_pct"],
        "litres": round(tank["level_pct"] / 100 * config.TANK_CAPACITY_LITRES),
        "sump_level_pct": tank.get("sump_level_pct"),
        "pump": {"on": bool(tank.get("pump_on")), "action": decision.action if decision else None,
                 "reason": decision.reason if decision else None},
        "next_pump": _next_pump(tank, decision, now),
        "next_supply": supply.isoformat(),
        "alerts": resident_alerts(tank, leak, state.scheduler.discom_paused, supply),
        "savings": _savings(building_id),
        "tariff": tariff_info(),
    }


# ---------------------------------------------------------------- demo controls (mock only)
class DemoCloud(BaseModel):
    active: bool


class DemoLeak(BaseModel):
    building_id: str
    active: bool


def _mock():
    if not state.live["mock_running"]:
        raise HTTPException(409, "demo controls need the in-process mock (no MQTT broker configured)")
    from mock import mock_generator
    return mock_generator


@router.get("/demo")
def demo_state():
    if not state.live["mock_running"]:
        return {"mock_running": False}
    return {"mock_running": True, **_mock().demo_state()}


@router.post("/demo/cloud")
def demo_cloud(req: DemoCloud):
    """Simulate covering the solar panel (the demo's cloud moment)."""
    _mock().set_cloud_override(req.active)
    return {"cloud": req.active}


@router.post("/demo/leak")
def demo_leak(req: DemoLeak):
    """Make one mock tank drain as if it had a leak."""
    m = _mock()
    if req.building_id not in m.building_ids():
        raise HTTPException(404, f"unknown mock building {req.building_id}")
    m.set_leak(req.building_id, req.active)
    return {"building_id": req.building_id, "leak": req.active}
