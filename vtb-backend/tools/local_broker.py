"""
A local MQTT broker in pure Python (amqtt) — no Mosquitto install needed.
Use it for demo day or for testing the hardware path end to end:

    python -m tools.local_broker                 # listens on 0.0.0.0:1883
    python -m tools.local_broker --port 1884     # another port

Then start the backend with VTB_MQTT_URL=mqtt://localhost:1883 and point the
ESP32s (or tools/fake_esp32.py) at this machine's IP.
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import warnings


def broker_config(host: str, port: int) -> dict:
    return {
        "listeners": {"default": {"type": "tcp", "bind": f"{host}:{port}"}},
        "sys_interval": 0,
        "auth": {"allow-anonymous": True},
        "topic-check": {"enabled": False},
    }


async def run(host: str, port: int):
    from amqtt.broker import Broker
    broker = Broker(broker_config(host, port))
    await broker.start()
    print(f"[local_broker] MQTT broker listening on {host}:{port} (Ctrl+C to stop)", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await broker.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("amqtt").setLevel(logging.ERROR)          # quiet amqtt's start-up chatter
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="amqtt")
    try:
        asyncio.run(run(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
