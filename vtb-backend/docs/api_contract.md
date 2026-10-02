# Virtual Tank Battery — Interface Contract

Share this with the hardware/firmware teammate on Day 1. Nothing here should
change without updating both sides.

## MQTT topics

| Topic | Direction | Payload |
|---|---|---|
| `vtb/tank/{id}/telemetry` | ESP32 → server | `{"level_pct": 42.5, "sump_level_pct": 70.0, "pump_on": false, "pump_w": 0.0, "ts": "2026-09-28T10:00:00+05:30"}` |
| `vtb/solar/telemetry` | ESP32 → server | `{"solar_w": 320.5, "lux": 6400.0, "ts": "2026-09-28T10:00:00Z"}` |
| `vtb/tank/{id}/cmd` | server → ESP32 | `{"action": "ON", "reason": "solar surplus (320W) — pumping in green hour"}` |
| `vtb/discom/pause` | dashboard → all | `{"active": true}` |

- `{id}` is the building/tank identifier, e.g. `tank-01`. Any id works — the backend subscribes with the wildcard `vtb/tank/+/telemetry`.
- `level_pct` is 0–100. `pump_w` is instantaneous pump power draw in watts.
- `sump_level_pct` (0–100) is **optional but strongly wanted**: dry-run protection is decided from the sump, not the overhead tank. If omitted, the backend skips the sump check and relies on firmware.
- `ts` is informational; the backend stamps its own receive time. All time-of-day logic runs in IST.
- Firmware should still enforce dry-run/overflow protection **locally** even if a `cmd` message never arrives (network drop) — see the "offline safety" note in the project plan.

## REST API (FastAPI backend)

| Endpoint | Method | Returns |
|---|---|---|
| `/health` | GET | `{"status": "ok"}` |
| `/tanks` | GET | Latest telemetry per tank |
| `/feeder/soc?feeder_id=feeder-1` | GET | `{feeder_id, soc_kwh, soc_pct_of_max, tanks_reporting}` |
| `/forecast?horizons=0,15,30,60` | GET | List of `{horizon_min, solar_w, feeder_load_w, discom_load_mw, solar_source, load_source}` |
| `/sources` | GET | Live feed health, which models are active, their held-out accuracy |
| `/loadcurve` | GET | Last 200 pump commands (building_id, action, reason, ts) |
| `/pause` | POST | Body `{"active": true/false}` — publishes `vtb/discom/pause` |
| `/simulate?n_buildings=300&cloudy_day=false` | GET | `{n_buildings, peak_reduction_pct, kwh_shifted, curve}` |
| `/ws/live` | WebSocket | Pushes `tank_telemetry`, `solar_telemetry`, `pump_commands`, `pause_state` events as they happen |

Full interactive docs at `http://localhost:8000/docs` once the server is running.

## What's mocked right now

By default there's no broker — `app/bus.py` provides an in-memory pub/sub
with MQTT topic semantics (`+`/`#` wildcards), and `mock/mock_generator.py`
runs inside the API process, publishing realistic fake telemetry for 8 tanks
(with sumps) + solar.

**To switch to real hardware:** run a broker (e.g. Mosquitto on the demo
laptop) and start the API with `VTB_MQTT_URL=mqtt://<host>:1883`. The mock
turns itself off automatically and nothing else changes — every consumer
only ever touches `bus.publish`/`bus.subscribe`.
