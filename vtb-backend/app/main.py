from __future__ import annotations
import asyncio
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import Base, engine, get_db, SessionLocal
from app import models, schemas, config
from app.bus import bus
from app.forecast import combined_forecast
from app.scheduler import Scheduler, TankSnapshot
from app.simulator import run_simulation

Base.metadata.create_all(bind=engine)

scheduler = Scheduler()
_ws_clients: set[WebSocket] = set()
_latest_cloud_factor = 1.0


async def _broadcast(payload: dict):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


async def on_tank_telemetry(topic: str, payload: dict):
    """Handles vtb/tank/{id}/telemetry from a real or mock ESP32."""
    building_id = topic.split("/")[2]
    db: Session = SessionLocal()
    try:
        if not db.get(models.Building, building_id):
            db.add(models.Building(id=building_id, name=building_id))
            db.commit()
        db.add(models.TankTelemetry(
            building_id=building_id,
            level_pct=payload["level_pct"],
            pump_on=payload["pump_on"],
            pump_w=payload["pump_w"],
        ))
        db.commit()
    finally:
        db.close()

    await _broadcast({"type": "tank_telemetry", "building_id": building_id, **payload})
    await _run_scheduler_tick()


async def on_solar_telemetry(topic: str, payload: dict):
    global _latest_cloud_factor
    db: Session = SessionLocal()
    try:
        db.add(models.SolarTelemetry(solar_w=payload["solar_w"], lux=payload["lux"]))
        db.commit()
    finally:
        db.close()

    from app.forecast import _solar_curve_w
    now = datetime.now(timezone.utc)
    clear_sky = _solar_curve_w(now.hour + now.minute / 60) or 1.0
    _latest_cloud_factor = max(0.05, min(1.5, payload["solar_w"] / clear_sky))

    await _broadcast({"type": "solar_telemetry", **payload})


async def on_discom_pause(topic: str, payload: dict):
    scheduler.set_pause(payload.get("active", False))
    await _broadcast({"type": "pause_state", "active": scheduler.discom_paused})
    await _run_scheduler_tick()


async def _run_scheduler_tick():
    db: Session = SessionLocal()
    try:
        latest_by_building: dict[str, models.TankTelemetry] = {}
        for row in db.query(models.TankTelemetry).order_by(desc(models.TankTelemetry.ts)).limit(500):
            latest_by_building.setdefault(row.building_id, row)

        latest_solar = db.query(models.SolarTelemetry).order_by(desc(models.SolarTelemetry.ts)).first()
        solar_w = latest_solar.solar_w if latest_solar else 0.0

        tanks = [TankSnapshot(bid, row.level_pct) for bid, row in latest_by_building.items()]
        if not tanks:
            return
        decisions = scheduler.decide(tanks, solar_w, datetime.now(timezone.utc), _latest_cloud_factor)

        for d in decisions:
            db.add(models.PumpCommand(building_id=d.building_id, action=d.action, reason=d.reason))
        db.commit()

        for d in decisions:
            await bus.publish(config.TOPIC_TANK_CMD.format(id=d.building_id),
                               {"action": d.action, "reason": d.reason})
        await _broadcast({"type": "pump_commands",
                           "commands": [{"building_id": d.building_id, "action": d.action, "reason": d.reason}
                                        for d in decisions]})
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.subscribe(config.TOPIC_SOLAR_TELEMETRY, on_solar_telemetry)
    bus.subscribe(config.TOPIC_DISCOM_PAUSE, on_discom_pause)
    # Per-building telemetry topics are subscribed to lazily as buildings appear;
    # for the mock/demo set we subscribe to a known pool up front.
    for i in range(1, 21):
        bid = f"tank-{i:02d}"
        bus.subscribe(config.TOPIC_TANK_TELEMETRY.format(id=bid), on_tank_telemetry)
    for i in range(20):
        bid = f"sim-{i:04d}"
        bus.subscribe(config.TOPIC_TANK_TELEMETRY.format(id=bid), on_tank_telemetry)

    mock_task = None
    if config.MQTT_BROKER_URL is None and os.environ.get("VTB_DISABLE_MOCK") != "1":
        # No real broker configured yet -> run the mock generator in-process so it
        # shares this exact Bus instance. Once hardware is ready, either set
        # MQTT_BROKER_URL or export VTB_DISABLE_MOCK=1 to turn this off.
        from mock.mock_generator import main as mock_main
        mock_task = asyncio.create_task(mock_main())

    yield

    if mock_task:
        mock_task.cancel()


app = FastAPI(title="Virtual Tank Battery API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tanks", response_model=list[schemas.TankState])
def get_tanks(db: Session = Depends(get_db)):
    latest: dict[str, models.TankTelemetry] = {}
    for row in db.query(models.TankTelemetry).order_by(desc(models.TankTelemetry.ts)).limit(1000):
        latest.setdefault(row.building_id, row)
    return list(latest.values())


@app.get("/feeder/soc", response_model=schemas.FeederSoC)
def feeder_soc(feeder_id: str = "feeder-1", db: Session = Depends(get_db)):
    latest: dict[str, models.TankTelemetry] = {}
    for row in db.query(models.TankTelemetry).order_by(desc(models.TankTelemetry.ts)).limit(1000):
        latest.setdefault(row.building_id, row)

    empty_capacity_l = sum(
        config.TANK_CAPACITY_LITRES * (100 - row.level_pct) / 100 for row in latest.values()
    )
    soc_kwh = empty_capacity_l * config.ENERGY_PER_LITRE_WH / 1000
    max_possible_kwh = len(latest) * config.TANK_CAPACITY_LITRES * config.ENERGY_PER_LITRE_WH / 1000
    pct = round(100 * soc_kwh / max_possible_kwh, 1) if max_possible_kwh else 0.0

    return schemas.FeederSoC(
        feeder_id=feeder_id, soc_kwh=round(soc_kwh, 2), soc_pct_of_max=pct,
        tanks_reporting=len(latest),
    )


@app.get("/forecast", response_model=list[schemas.ForecastPoint])
def forecast(horizons: str = "0,15,30,60"):
    horizons_min = [int(h) for h in horizons.split(",")]
    now = datetime.now(timezone.utc)
    return combined_forecast(now, horizons_min, _latest_cloud_factor)


@app.get("/loadcurve")
def loadcurve(db: Session = Depends(get_db)):
    """Last 100 pump-command ticks, useful for a live-updating chart before
    the full simulator numbers are wired in."""
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
