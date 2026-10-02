import os
import time

os.environ["VTB_DISABLE_MOCK"] = "0"
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
        assert len(client.get("/forecast").json()) == 4
