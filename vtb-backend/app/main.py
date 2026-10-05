from __future__ import annotations
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import numpy as np
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import Base, engine, get_db, SessionLocal
from app import models, schemas, config, state
from app.bus import bus, MqttBus
from app.clock import now_ist
from app.forecast import combined_forecast, model_info, panel_clearness
from app import live_data
from app.headroom import pumps_allowed, valley_ceiling
from app.scheduler import TankSnapshot
from app.simulator import run_simulation
from app.soc import feeder_soc as compute_feeder_soc, fillable_litres

Base.metadata.create_all(bind=engine)

log = logging.getLogger("vtb")
_ws_clients: set[WebSocket] = set()


async def broadcast(payload: dict):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


def save_setting(key: str, value: str):
    db: Session = SessionLocal()
    try:
        db.merge(models.Setting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def load_setting(key: str) -> str | None:
    db: Session = SessionLocal()
    try:
        row = db.get(models.Setting, key)
        return row.value if row else None
    finally:
        db.close()


def k_prev(now: datetime) -> float | None:
    """Panel clearness about an hour ago (±10 min), for the solar model."""
    target = now - timedelta(hours=1)
    best = min(state.clearness_history, key=lambda p: abs((p[0] - target).total_seconds()), default=None)
    if best is None or abs((best[0] - target).total_seconds()) > 600:
        return None
    return best[1]


async def on_tank_telemetry(topic: str, payload: dict):
    """Handles vtb/tank/{id}/telemetry from a real or mock ESP32. Stores and
    broadcasts only — the scheduler runs on its own fixed tick."""
    building_id = topic.split("/")[2]
    try:
        level_pct = float(payload["level_pct"])
        pump_on = bool(payload["pump_on"])
        pump_w = float(payload.get("pump_w", 0.0))
        sump = payload.get("sump_level_pct")
        sump = float(sump) if sump is not None else None
    except (KeyError, TypeError, ValueError):
        log.warning("bad telemetry on %s: %r", topic, payload)
        return

    now = now_ist()
    state.latest_tanks[building_id] = {"building_id": building_id, "level_pct": level_pct, "pump_on": pump_on,
                                       "pump_w": pump_w, "sump_level_pct": sump, "ts": models.now()}
    state.leaks.observe(building_id, level_pct, pump_on, now)

    db: Session = SessionLocal()
    try:
        if not db.get(models.Building, building_id):
            db.add(models.Building(id=building_id, name=building_id))
            db.commit()
        db.add(models.TankTelemetry(
            building_id=building_id,
            level_pct=level_pct,
            pump_on=pump_on,
            pump_w=pump_w,
            sump_level_pct=sump,
        ))
        db.commit()
    finally:
        db.close()

    await broadcast({"type": "tank_telemetry", "building_id": building_id, **payload})


async def on_solar_telemetry(topic: str, payload: dict):
    try:
        solar_w = float(payload["solar_w"])
    except (KeyError, TypeError, ValueError):
        log.warning("bad solar telemetry: %r", payload)
        return
    db: Session = SessionLocal()
    try:
        db.add(models.SolarTelemetry(solar_w=solar_w, lux=payload.get("lux")))
        db.commit()
    finally:
        db.close()

    now = now_ist()
    state.live["solar_w"] = solar_w
    state.live["clearness"] = panel_clearness(solar_w, now)
    if state.live["clearness"] is not None:
        state.clearness_history.append((now, state.live["clearness"]))

    await broadcast({"type": "solar_telemetry", **payload})


async def on_discom_pause(topic: str, payload: dict):
    active = bool(payload.get("active", False))
    if active and not state.scheduler.discom_paused:
        shed = sum(float(t.get("pump_w") or 0) for t in state.latest_tanks.values() if t.get("pump_on"))
        state.impact.record_pause(now_ist(), shed)
    state.scheduler.set_pause(active)
    save_setting("discom_paused", "1" if active else "0")
    await broadcast({"type": "pause_state", "active": active})
    await run_scheduler_tick()   # act immediately, don't wait for the next tick


_headroom_cache: dict = {"minute": None, "pumps": None}


def headroom_pumps(now: datetime) -> int | None:
    """How many pumps may run now, from the 6 h load + solar forecast (demo watts): valley-fill
    the coming solar hours, never above the forecast peak (app/headroom.py). Recomputed once a
    minute. None = no limit."""
    minute = now.replace(second=0, microsecond=0)
    if _headroom_cache["minute"] != minute:
        try:
            fc = combined_forecast(now, list(range(0, 361, 30)), state.live["clearness"], k_prev(now))
            state.live["feeder_load_w"] = fc[0]["feeder_load_w"]
            net = np.array([p["feeder_load_w"] - p["solar_w"] for p in fc])
            green = np.array([p["solar_w"] >= config.SOLAR_SURPLUS_THRESHOLD_W for p in fc])
            need_l = sum(fillable_litres(t["level_pct"], t["sump_level_pct"]) for t in state.latest_tanks.values())
            ceiling = valley_ceiling(net, green, config.PUMP_RATED_W, need_l / config.SIM_PUMP_FLOW_LPH, 0.5)
            _headroom_cache["pumps"] = pumps_allowed(net[0], ceiling if green[0] else net.max(), config.PUMP_RATED_W)
        except Exception:
            log.exception("headroom forecast failed — running without a cap")
            _headroom_cache["pumps"] = None
        _headroom_cache["minute"] = minute
    return _headroom_cache["pumps"]


_last_tick_mono: list[float] = []


async def run_scheduler_tick():
    if not state.latest_tanks:
        return
    now = now_ist()
    mono = time.monotonic()
    dt = min(mono - _last_tick_mono[0], 30.0) if _last_tick_mono else 0.0
    _last_tick_mono[:] = [mono]

    tanks = list(state.latest_tanks.values())
    state.impact.tick(now, tanks, state.live["solar_w"], state.live["feeder_load_w"],
                      state.scheduler.discom_paused, dt)

    snaps = [TankSnapshot(t["building_id"], t["level_pct"], t["sump_level_pct"], t["pump_on"]) for t in tanks]
    decisions = state.scheduler.decide(snaps, state.live["solar_w"], now, state.live["clearness"], k_prev(now),
                                       max_running=headroom_pumps(now))
    state.last_decisions = {d.building_id: d for d in decisions}

    changed = [d for d in decisions if state.last_sent.get(d.building_id, ("", 0))[0] != d.action]
    refresh = [d for d in decisions if d not in changed
               and mono - state.last_sent.get(d.building_id, ("", 0))[1] >= config.CMD_REFRESH_SEC]

    if changed:
        db: Session = SessionLocal()
        try:
            for d in changed:
                db.add(models.PumpCommand(building_id=d.building_id, action=d.action, reason=d.reason))
            db.commit()
        finally:
            db.close()

    for d in changed + refresh:
        state.last_sent[d.building_id] = (d.action, mono)
        await bus.publish(config.TOPIC_TANK_CMD.format(id=d.building_id), {"action": d.action, "reason": d.reason})

    # The dashboard gets every decision each tick — reasons change even when actions don't
    await broadcast({"type": "pump_commands",
                     "commands": [{"building_id": d.building_id, "action": d.action, "reason": d.reason}
                                  for d in decisions]})


async def _scheduler_loop():
    ticks = 0
    while True:
        try:
            await run_scheduler_tick()
            ticks += 1
            if ticks % 6 == 0:          # persist today's impact totals every ~30 s
                state.impact.persist()
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(config.SCHEDULER_TICK_SEC)


def _load_latest_from_db():
    """Warm start: recover the last known state so a restart doesn't begin blind."""
    db: Session = SessionLocal()
    try:
        for row in db.query(models.TankTelemetry).order_by(desc(models.TankTelemetry.ts)).limit(1000):
            state.latest_tanks.setdefault(row.building_id, {
                "building_id": row.building_id, "level_pct": row.level_pct, "pump_on": row.pump_on,
                "pump_w": row.pump_w, "sump_level_pct": row.sump_level_pct, "ts": row.ts})
    finally:
        db.close()
    state.scheduler.set_pause(load_setting("discom_paused") == "1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_latest_from_db()
    bus.subscribe(config.TOPIC_SOLAR_TELEMETRY, on_solar_telemetry)
    bus.subscribe(config.TOPIC_DISCOM_PAUSE, on_discom_pause)
    # One wildcard subscription covers every tank, whatever id the firmware uses.
    bus.subscribe(config.TOPIC_TANK_TELEMETRY.format(id="+"), on_tank_telemetry)

    if isinstance(bus, MqttBus):
        bus.start(asyncio.get_running_loop())

    tasks = [asyncio.create_task(_scheduler_loop())]
    if config.MQTT_BROKER_URL is None and os.environ.get("VTB_DISABLE_MOCK") != "1":
        # No real broker configured -> run the mock generator in-process so it
        # shares this exact Bus instance. Set VTB_MQTT_URL or VTB_DISABLE_MOCK=1
        # to turn this off.
        from mock import mock_generator
        config.TELEMETRY_TIME_SCALE = mock_generator.SPEEDUP
        state.live["mock_running"] = True
        tasks.append(asyncio.create_task(mock_generator.main()))

    yield

    for t in tasks:
        t.cancel()
    state.live["mock_running"] = False
    state.impact.persist()
    if isinstance(bus, MqttBus):
        bus.stop()


app = FastAPI(title="Virtual Tank Battery API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

from app.routes import router  # noqa: E402  (routes import helpers defined above)
app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sources")
def sources():
    """Which data path is live right now, plus the trained models' held-out
    accuracy vs baselines — so every number on the dashboard is traceable."""
    return {"location": {"city": config.CITY, "lat": config.LATITUDE, "lon": config.LONGITUDE},
            "feeds": live_data.status(), "models": model_info(),
            "panel_clearness": state.live["clearness"], "mock_running": state.live["mock_running"]}


@app.get("/tanks", response_model=list[schemas.TankState])
def get_tanks():
    return sorted(state.latest_tanks.values(), key=lambda t: t["building_id"])


@app.get("/feeder/soc", response_model=schemas.FeederSoC)
def feeder_soc(feeder_id: str = "feeder-1", db: Session = Depends(get_db)):
    on_feeder = {b.id for b in db.query(models.Building).filter(models.Building.feeder_id == feeder_id)}
    tanks = [t for bid, t in state.latest_tanks.items() if bid in on_feeder]
    return schemas.FeederSoC(feeder_id=feeder_id, **compute_feeder_soc(tanks, now_ist()))


@app.get("/forecast", response_model=list[schemas.ForecastPoint])
def forecast(horizons: str = "0,15,30,60"):
    horizons_min = [int(h) for h in horizons.split(",")]
    now = now_ist()
    return combined_forecast(now, horizons_min, state.live["clearness"], k_prev(now))


@app.get("/simulate", response_model=schemas.SimulationResult)
def simulate(n_buildings: int = config.DEFAULT_SIM_BUILDINGS, cloudy_day: bool = False):
    return run_simulation(n_buildings, cloudy_day=cloudy_day)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    await websocket.send_json({"type": "pause_state", "active": state.scheduler.discom_paused})
    try:
        while True:
            await websocket.receive_text()  # keep-alive; client doesn't need to send anything meaningful
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)
