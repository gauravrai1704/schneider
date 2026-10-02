"""
Publishes fake tank + solar telemetry onto the shared in-memory Bus, in the
EXACT payload shape the real ESP32 firmware will send over MQTT. This is
what lets the backend + dashboard be built and demoed without waiting on
hardware.

Runs automatically inside the API process when no broker is configured.
Swap for the real ESP32s later — nothing else in the codebase changes,
since consumers only ever see the topic + payload, never the source.
"""
import asyncio
import random

from app.bus import bus
from app import config
from app.clock import hour_float, now_ist
from app.forecast import current_sky_w
from app.water import draw_litres_per_hr

N_TANKS = 8
TICK_SECONDS = 2
# Real tanks drain over hours; speed water use up so level changes are visible on stage.
SPEEDUP = 60
PUMP_FILL_PCT_PER_TICK = 2.5
SUMP_CAPACITY_RATIO = 5          # ground sump holds ~5x the overhead tank
# Municipal supply windows (IST hours) — when the sump refills fastest
MUNICIPAL_WINDOWS = [(6, 8), (18, 19)]

_state = {f"tank-{i:02d}": {"level_pct": random.uniform(30, 80),
                            "sump_level_pct": random.uniform(50, 90),
                            "pump_on": False}
          for i in range(1, N_TANKS + 1)}
_cloud_override = {"active": False}  # toggled for the demo's "cover the panel" moment


def _sump_inflow_pct(h: float) -> float:
    in_window = any(start <= h < end for start, end in MUNICIPAL_WINDOWS)
    # outside the windows a slow trickle keeps the mock from stalling the demo
    return 0.6 if in_window else 0.3


async def _tick():
    now = now_ist()
    h = hour_float(now)
    # Follows the real sky over Delhi right now (live Open-Meteo irradiance), with sensor noise
    sky_w = current_sky_w(now)
    solar_w = sky_w * (0.15 if _cloud_override["active"] else random.uniform(0.95, 1.05))

    await bus.publish(config.TOPIC_SOLAR_TELEMETRY, {
        "solar_w": round(solar_w, 1),
        "lux": round(solar_w * 20, 1),
        "ts": now.isoformat(),
    })

    for bid, s in _state.items():
        draw_l = draw_litres_per_hr(now, bid) * TICK_SECONDS / 3600 * SPEEDUP
        s["level_pct"] = max(0.0, s["level_pct"] - 100 * draw_l / config.TANK_CAPACITY_LITRES)
        s["sump_level_pct"] = min(100.0, s["sump_level_pct"] + _sump_inflow_pct(h))
        if s["pump_on"] and s["sump_level_pct"] > 0:
            s["level_pct"] = min(100.0, s["level_pct"] + PUMP_FILL_PCT_PER_TICK)
            s["sump_level_pct"] = max(0.0, s["sump_level_pct"] - PUMP_FILL_PCT_PER_TICK / SUMP_CAPACITY_RATIO)
        payload = {
            "level_pct": round(s["level_pct"], 1),
            "sump_level_pct": round(s["sump_level_pct"], 1),
            "pump_on": s["pump_on"],
            "pump_w": 40.0 if s["pump_on"] else 0.0,
            "ts": now.isoformat(),
        }
        await bus.publish(config.TOPIC_TANK_TELEMETRY.format(id=bid), payload)


def _apply_commands():
    """Mirrors what real firmware does: listen for vtb/tank/{id}/cmd and flip
    the pump relay accordingly."""
    def make_handler(bid):
        async def handler(topic, payload):
            _state[bid]["pump_on"] = payload["action"] == "ON"
        return handler

    for bid in _state:
        bus.subscribe(config.TOPIC_TANK_CMD.format(id=bid), make_handler(bid))


async def main():
    _apply_commands()
    print(f"[mock_generator] publishing telemetry for {N_TANKS} tanks every {TICK_SECONDS}s")
    while True:
        await _tick()
        await asyncio.sleep(TICK_SECONDS)


def set_cloud_override(active: bool):
    """Call this from a demo script / debug endpoint to simulate 'covering the panel'."""
    _cloud_override["active"] = active


if __name__ == "__main__":
    asyncio.run(main())
