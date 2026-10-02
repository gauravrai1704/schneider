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
        fc = client.get("/forecast").json()
        assert len(fc) == 4 and {"solar_source", "load_source"} <= fc[0].keys()
        src = client.get("/sources").json()
        assert src["feeds"]["offline_mode"] is True and "models" in src
