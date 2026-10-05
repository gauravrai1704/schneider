"""
End-to-end over a real MQTT broker: local broker + backend in separate
processes, this test playing the ESP32. Proves the hardware path works
exactly as documented in docs/api_contract.md.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

pytest.importorskip("amqtt", reason="amqtt not installed (pip install -r requirements-dev.txt)")
import paho.mqtt.client as mqtt  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture
def stack(tmp_path):
    broker_port, api_port = _free_port(), _free_port()
    env = {**os.environ, "PYTHONPATH": BACKEND, "VTB_OFFLINE": "1",
           "VTB_MQTT_URL": f"mqtt://127.0.0.1:{broker_port}"}
    procs = [subprocess.Popen([sys.executable, "-m", "tools.local_broker", "--host", "127.0.0.1",
                               "--port", str(broker_port)], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    time.sleep(2)
    # cwd = tmp_path gives the backend its own throwaway SQLite database
    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(api_port)],
                                  cwd=tmp_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        assert _wait_http(f"http://127.0.0.1:{api_port}/health", 60), "backend did not start"
        yield broker_port, f"http://127.0.0.1:{api_port}"
    finally:
        for p in reversed(procs):
            p.terminate()
            p.wait(10)


def test_esp32_over_mqtt(stack):
    broker_port, api = stack
    commands, pause_msgs = [], []
    got_cmd = threading.Event()

    def on_message(client, userdata, msg):
        payload = json.loads(msg.payload)
        if msg.topic.endswith("/cmd"):
            commands.append(payload)
            got_cmd.set()
        elif msg.topic == "vtb/discom/pause":
            pause_msgs.append(payload)

    esp = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    esp.on_message = on_message
    esp.connect("127.0.0.1", broker_port)
    esp.subscribe("vtb/tank/e2e-01/cmd")
    esp.subscribe("vtb/discom/pause")
    esp.loop_start()
    try:
        # A low tank with water in the sump must be told to refill, whatever the sun is doing
        telemetry = {"level_pct": 5.0, "sump_level_pct": 80.0, "pump_on": False, "pump_w": 0.0}
        deadline = time.time() + 30
        while not got_cmd.is_set() and time.time() < deadline:
            esp.publish("vtb/tank/e2e-01/telemetry", json.dumps(telemetry))
            esp.publish("vtb/solar/telemetry", json.dumps({"solar_w": 0.0, "lux": 0.0}))
            got_cmd.wait(1)
        assert commands, "no command arrived over MQTT"
        assert commands[0]["action"] == "ON" and "safe minimum" in commands[0]["reason"]

        tanks = httpx.get(f"{api}/tanks").json()
        assert any(t["building_id"] == "e2e-01" and t["sump_level_pct"] == 80.0 for t in tanks)

        # Pump Pause goes dashboard -> broker -> every subscriber, including the backend itself
        assert httpx.post(f"{api}/pause", json={"active": True}).json() == {"active": True}
        for _ in range(20):
            if httpx.get(f"{api}/pause").json()["active"] and pause_msgs:
                break
            time.sleep(0.25)
        assert pause_msgs and pause_msgs[-1] == {"active": True}
        assert httpx.get(f"{api}/pause").json() == {"active": True}
    finally:
        esp.loop_stop()
        esp.disconnect()
