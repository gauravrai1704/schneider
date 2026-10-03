from __future__ import annotations
import asyncio
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import Base, engine, get_db, SessionLocal
from app import models, schemas, config
from app.bus import bus, MqttBus
from app.clock import now_ist
from app.forecast import combined_forecast, model_info, panel_clearness
from app import live_data
from app.scheduler import Scheduler, TankSnapshot
from app.simulator import run_simulation
from app.soc import feeder_soc as compute_feeder_soc, fillable_litres
from app.headroom import pumps_allowed, valley_ceiling
import numpy as np

Base.metadata.create_all(bind=engine)

log = logging.getLogger("vtb")
scheduler = Scheduler()
_ws_clients: set[WebSocket] = set()

# Latest state, kept in memory for the control loop (the DB keeps the history)
_latest_tanks: dict[str, dict] = {}
_latest_solar_w: float = 0.0
_latest_cloud_factor: float | None = None   # panel clearness index; None = unknown/night
_clearness_history: deque[tuple[datetime, float]] = deque(maxlen=2000)  # ~70 min at 2 s
# What each pump was last told, and when — commands go out only on change (plus a periodic refresh)
_last_sent: dict[str, tuple[str, float]] = {}


async def _broadcast(payload: dict):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


def _k_prev(now: datetime) -> float | None:
    """Panel clearness about an hour ago (±10 min), for the solar model."""
    target = now - timedelta(hours=1)
    best = min(_clearness_history, key=lambda p: abs((p[0] - target).total_seconds()), default=None)
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

    _latest_tanks[building_id] = {"building_id": building_id, "level_pct": level_pct, "pump_on": pump_on,
                                  "pump_w": pump_w, "sump_level_pct": sump, "ts": models.now()}

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

    await _broadcast({"type": "tank_telemetry", "building_id": building_id, **payload})


async def on_solar_telemetry(topic: str, payload: dict):
    global _latest_cloud_factor, _latest_solar_w
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
    _latest_solar_w = solar_w
    _latest_cloud_factor = panel_clearness(solar_w, now)
    if _latest_cloud_factor is not None:
        _clearness_history.append((now, _latest_cloud_factor))

    await _broadcast({"type": "solar_telemetry", **payload})


async def on_discom_pause(topic: str, payload: dict):
    scheduler.set_pause(payload.get("active", False))
    await _broadcast({"type": "pause_state", "active": scheduler.discom_paused})
    await _run_scheduler_tick()   # act immediately, don't wait for the next tick


_headroom_cache: dict = {"minute": None, "pumps": None}


def _headroom_pumps(now: datetime) -> int | None:
    """How many pumps may run now, from the 6 h load + solar forecast (demo watts): valley-fill
    the coming solar hours, never above the forecast peak (app/headroom.py). Recomputed once a
    minute. None = no limit."""
    minute = now.replace(second=0, microsecond=0)
    if _headroom_cache["minute"] != minute:
        try:
            fc = combined_forecast(now, list(range(0, 361, 30)), _latest_cloud_factor, _k_prev(now))
            net = np.array([p["feeder_load_w"] - p["solar_w"] for p in fc])
            green = np.array([p["solar_w"] >= config.SOLAR_SURPLUS_THRESHOLD_W for p in fc])
            need_l = sum(fillable_litres(t["level_pct"], t["sump_level_pct"]) for t in _latest_tanks.values())
            ceiling = valley_ceiling(net, green, config.PUMP_RATED_W, need_l / config.SIM_PUMP_FLOW_LPH, 0.5)
            _headroom_cache["pumps"] = pumps_allowed(net[0], ceiling if green[0] else net.max(), config.PUMP_RATED_W)
        except Exception:
            log.exception("headroom forecast failed — running without a cap")
            _headroom_cache["pumps"] = None
        _headroom_cache["minute"] = minute
    return _headroom_cache["pumps"]


async def _run_scheduler_tick():
    if not _latest_tanks:
        return
    now = now_ist()
    tanks = [TankSnapshot(t["building_id"], t["level_pct"], t["sump_level_pct"], t["pump_on"])
             for t in _latest_tanks.values()]
    decisions = scheduler.decide(tanks, _latest_solar_w, now, _latest_cloud_factor, _k_prev(now),
                                 max_running=_headroom_pumps(now))

    mono = time.monotonic()
    changed = [d for d in decisions if _last_sent.get(d.building_id, ("", 0))[0] != d.action]
    refresh = [d for d in decisions if d not in changed
               and mono - _last_sent.get(d.building_id, ("", 0))[1] >= config.CMD_REFRESH_SEC]

    if changed:
        db: Session = SessionLocal()
        try:
            for d in changed:
                db.add(models.PumpCommand(building_id=d.building_id, action=d.action, reason=d.reason))
            db.commit()
        finally:
            db.close()

    for d in changed + refresh:
        _last_sent[d.building_id] = (d.action, mono)
        await bus.publish(config.TOPIC_TANK_CMD.format(id=d.building_id), {"action": d.action, "reason": d.reason})

    # The dashboard gets every decision each tick — reasons change even when actions don't
    await _broadcast({"type": "pump_commands",
                      "commands": [{"building_id": d.building_id, "action": d.action, "reason": d.reason}
                                   for d in decisions]})


async def _scheduler_loop():
    while True:
        try:
            await _run_scheduler_tick()
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(config.SCHEDULER_TICK_SEC)


def _load_latest_from_db():
    """Warm start: recover the last known state so a restart doesn't begin blind."""
    db: Session = SessionLocal()
    try:
        for row in db.query(models.TankTelemetry).order_by(desc(models.TankTelemetry.ts)).limit(1000):
            _latest_tanks.setdefault(row.building_id, {
                "building_id": row.building_id, "level_pct": row.level_pct, "pump_on": row.pump_on,
                "pump_w": row.pump_w, "sump_level_pct": row.sump_level_pct, "ts": row.ts})
    finally:
        db.close()


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
        from mock.mock_generator import main as mock_main
        tasks.append(asyncio.create_task(mock_main()))

    yield

    for t in tasks:
        t.cancel()
    if isinstance(bus, MqttBus):
        bus.stop()


app = FastAPI(title="Virtual Tank Battery API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sources")
def sources():
    """Which data path is live right now, plus the trained models' held-out
    accuracy vs baselines — so every number on the dashboard is traceable."""
    return {"location": {"city": config.CITY, "lat": config.LATITUDE, "lon": config.LONGITUDE},
            "feeds": live_data.status(), "models": model_info(),
            "panel_clearness": _latest_cloud_factor}


@app.get("/tanks", response_model=list[schemas.TankState])
def get_tanks():
    return sorted(_latest_tanks.values(), key=lambda t: t["building_id"])


@app.get("/feeder/soc", response_model=schemas.FeederSoC)
def feeder_soc(feeder_id: str = "feeder-1", db: Session = Depends(get_db)):
    on_feeder = {b.id for b in db.query(models.Building).filter(models.Building.feeder_id == feeder_id)}
    tanks = [t for bid, t in _latest_tanks.items() if bid in on_feeder]
    return schemas.FeederSoC(feeder_id=feeder_id, **compute_feeder_soc(tanks, now_ist()))


@app.get("/forecast", response_model=list[schemas.ForecastPoint])
def forecast(horizons: str = "0,15,30,60"):
    horizons_min = [int(h) for h in horizons.split(",")]
    now = now_ist()
    return combined_forecast(now, horizons_min, _latest_cloud_factor, _k_prev(now))


@app.get("/loadcurve")
def loadcurve(db: Session = Depends(get_db)):
    """Recent pump-command changes, newest first."""
    rows = db.query(models.PumpCommand).order_by(desc(models.PumpCommand.ts)).limit(200).all()
    return [{"building_id": r.building_id, "action": r.action, "reason": r.reason, "ts": r.ts} for r in rows]


@app.post("/pause")
async def pause(req: schemas.PauseRequest):
    await bus.publish(config.TOPIC_DISCOM_PAUSE, {"active": req.active})
    return {"active": req.active}


@app.get("/simulate", response_model=schemas.SimulationResult)
def simulate(n_buildings: int = config.DEFAULT_SIM_BUILDINGS, cloudy_day: bool = False):
    return run_simulation(n_buildings, cloudy_day=cloudy_day)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive; client doesn't need to send anything meaningful
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)
