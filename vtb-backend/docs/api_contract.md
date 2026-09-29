# Virtual Tank Battery — Interface Contract

Share this with the hardware/firmware teammate on Day 1. Nothing here should
change without updating both sides.

## MQTT topics

| Topic | Direction | Payload |
|---|---|---|
| `vtb/tank/{id}/telemetry` | ESP32 → server | `{"level_pct": 42.5, "pump_on": false, "pump_w": 0.0, "ts": "2026-09-28T10:00:00Z"}` |
| `vtb/solar/telemetry` | ESP32 → server | `{"solar_w": 320.5, "lux": 6400.0, "ts": "2026-09-28T10:00:00Z"}` |
| `vtb/tank/{id}/cmd` | server → ESP32 | `{"action": "ON", "reason": "solar surplus (320W) — pumping in green hour"}` |
| `vtb/discom/pause` | dashboard → all | `{"active": true}` |

- `{id}` is the building/tank identifier, e.g. `tank-01`. Pick real IDs and tell the backend so they can be pre-subscribed (or ping the backend team to make subscription dynamic).
- `level_pct` is 0–100. `pump_w` is instantaneous pump power draw in watts.
- Firmware should still enforce dry-run/overflow protection **locally** even if a `cmd` message never arrives (network drop) — see the "offline safety" note in the project plan.

## REST API (FastAPI backend)

| Endpoint | Method | Returns |
|---|---|---|
| `/health` | GET | `{"status": "ok"}` |
| `/tanks` | GET | Latest telemetry per tank |
| `/feeder/soc?feeder_id=feeder-1` | GET | `{feeder_id, soc_kwh, soc_pct_of_max, tanks_reporting}` |
| `/forecast?horizons=0,15,30,60` | GET | List of `{horizon_min, solar_w, feeder_load_w}` |
| `/loadcurve` | GET | Last 200 pump commands (building_id, action, reason, ts) |
| `/pause` | POST | Body `{"active": true/false}` — publishes `vtb/discom/pause` |
| `/simulate?n_buildings=300&cloudy_day=false` | GET | `{n_buildings, peak_reduction_pct, kwh_shifted, curve}` |
| `/ws/live` | WebSocket | Pushes `tank_telemetry`, `solar_telemetry`, `pump_commands`, `pause_state` events as they happen |

Full interactive docs at `http://localhost:8000/docs` once the server is running.

## What's mocked right now

There's no real MQTT broker connected yet — `app/bus.py` provides an
in-memory pub/sub with the identical `publish`/`subscribe` interface, and
`mock/mock_generator.py` runs automatically inside the API process,
publishing realistic fake telemetry for 8 tanks + solar.

**To switch to real hardware:** set `MQTT_BROKER_URL` in `app/config.py` to
the broker address, swap `bus = Bus()` for `bus = MqttBus(...)` in
`app/bus.py`, and export `VTB_DISABLE_MOCK=1`. No other file needs to change
— every consumer only ever touches `bus.publish`/`bus.subscribe`.
