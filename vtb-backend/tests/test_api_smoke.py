import os
import time

os.environ["VTB_DISABLE_MOCK"] = "0"
os.environ["VTB_OFFLINE"] = "1"   # no network in tests
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_live_loop_with_mock_telemetry():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        time.sleep(2.5)  # let the mock publish at least one tick
        tanks = client.get("/tanks").json()
        assert len(tanks) >= 8
        assert all(t["sump_level_pct"] is not None for t in tanks)
        soc = client.get("/feeder/soc").json()
        assert soc["tanks_reporting"] >= 8
        assert {"pumps_running", "sheddable_w", "pause_minutes_available"} <= soc.keys()
        fc = client.get("/forecast").json()
        assert len(fc) == 4 and {"solar_source", "load_source"} <= fc[0].keys()
        src = client.get("/sources").json()
        assert src["feeds"]["offline_mode"] is True and "models" in src


def test_scheduler_loop_sends_commands_only_on_change():
    from collections import Counter
    from app import models, state
    from app.database import SessionLocal

    # Fresh-process state: earlier tests in this session already sent commands
    state.last_sent.clear()
    state.scheduler.commanded_on.clear()
    db = SessionLocal()
    start_id = db.query(models.PumpCommand.id).order_by(models.PumpCommand.id.desc()).first()
    start_id = start_id[0] if start_id else 0
    db.close()

    with TestClient(app):
        time.sleep(12)   # mock telemetry + ~2 scheduler ticks
        db = SessionLocal()
        rows = db.query(models.PumpCommand).filter(models.PumpCommand.id > start_id).all()
        db.close()
        assert rows, "scheduler loop produced no commands"
        per_building = Counter(r.building_id for r in rows)
        # first command per pump + at most a held->started pair; never one per telemetry message
        assert max(per_building.values()) <= 3, per_building
        assert set(state.last_sent) >= set(per_building)
