"""
Publishes fake tank + solar telemetry onto the shared in-memory Bus, in the
EXACT payload shape the real ESP32 firmware will send over MQTT. This is
what lets the backend + dashboard be built and demoed all week without
waiting on hardware.

Run alongside the API: `python -m mock.mock_generator` (see README).
Swap for the real ESP32s later — nothing else in the codebase changes,
since consumers only ever see the topic + payload, never the source.
"""
import asyncio
import random
from datetime import datetime, timezone

from app.bus import bus
from app import config
from app.forecast import _solar_curve_w

N_TANKS = 8
TICK_SECONDS = 2

_state = {f"tank-{i:02d}": {"level_pct": random.uniform(30, 80), "pump_on": False}
          for i in range(1, N_TANKS + 1)}
_cloud_override = {"active": False}  # toggled by /mock/cloud for the demo's "cover the panel" moment


async def _tick():
    now = datetime.now(timezone.utc)
    hour_float = now.hour + now.minute / 60
    clear_sky = _solar_curve_w(hour_float)
    solar_w = clear_sky * (0.15 if _cloud_override["active"] else random.uniform(0.85, 1.0))

    await bus.publish(config.TOPIC_SOLAR_TELEMETRY, {
        "solar_w": round(solar_w, 1),
        "lux": round(solar_w * 20, 1),
        "ts": now.isoformat(),
    })

    for bid, s in _state.items():
        draw = random.uniform(0.05, 0.3)
        s["level_pct"] = max(0.0, s["level_pct"] - draw)
        if s["pump_on"]:
            s["level_pct"] = min(100.0, s["level_pct"] + 2.5)
        payload = {
            "level_pct": round(s["level_pct"], 1),
            "pump_on": s["pump_on"],
            "pump_w": 40.0 if s["pump_on"] else 0.0,
            "ts": now.isoformat(),
        }
        await bus.publish(config.TOPIC_TANK_TELEMETRY.format(id=bid), payload)


async def _apply_commands():
    """Mirrors what real firmware does: listen for vtb/tank/{id}/cmd and flip
    the pump relay accordingly."""
    async def make_handler(bid):
        async def handler(topic, payload):
            _state[bid]["pump_on"] = payload["action"] == "ON"
        return handler

    for bid in _state:
        bus.subscribe(config.TOPIC_TANK_CMD.format(id=bid), await make_handler(bid))


async def main():
    await _apply_commands()
    print(f"[mock_generator] publishing telemetry for {N_TANKS} tanks every {TICK_SECONDS}s")
    while True:
        await _tick()
        await asyncio.sleep(TICK_SECONDS)


def set_cloud_override(active: bool):
    """Call this from a demo script / debug endpoint to simulate 'covering the panel'."""
    _cloud_override["active"] = active


if __name__ == "__main__":
    asyncio.run(main())
