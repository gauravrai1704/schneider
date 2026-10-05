"""
Fake ESP32s over a real MQTT broker: runs the same mock buildings the backend
uses in-process, but as a separate program talking MQTT — exactly the topics
and payloads the real firmware uses (docs/api_contract.md).

Use it to rehearse the hardware path, or to sit alongside real ESP32s:

    python -m tools.local_broker                                  # terminal 1
    set VTB_MQTT_URL=mqtt://localhost:1883 && uvicorn app.main:app  # terminal 2 (PowerShell: $env:VTB_MQTT_URL=...)
    python -m tools.fake_esp32 --broker mqtt://localhost:1883      # terminal 3
"""
from __future__ import annotations
import argparse
import asyncio
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broker", default=os.environ.get("VTB_MQTT_URL", "mqtt://localhost:1883"))
    args = parser.parse_args()
    # The shared bus is chosen from this env var at import time, so set it first
    os.environ["VTB_MQTT_URL"] = args.broker

    from app.bus import MqttBus, bus
    from mock import mock_generator

    if not isinstance(bus, MqttBus):
        raise SystemExit("VTB_MQTT_URL did not select the MQTT bus")

    async def run():
        bus.start(asyncio.get_running_loop())
        for _ in range(50):                      # wait up to ~10 s for the broker connection
            if bus._client.is_connected():
                break
            await asyncio.sleep(0.2)
        else:
            raise SystemExit(f"could not connect to {args.broker}")
        print(f"[fake_esp32] connected to {args.broker}", flush=True)
        await mock_generator.main()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
