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
- `sump_level_pct` (0–100) is **expected on every message** — each building reports its own ground sump. Dry-run protection is decided from the sump, not the overhead tank. If a message omits it, the backend skips the server-side sump check for that tick and relies on the firmware's local protection.
- `ts` is informational; the backend stamps its own receive time. All time-of-day logic runs in IST.
- **Commands (`vtb/tank/{id}/cmd`)** are sent when a pump's decision changes, and re-sent unchanged every 60 s. Firmware should treat ~3 missed refreshes (no command for 3 min) as "server offline" and fall back to its local rules: keep the tank above the safe minimum, never run with an empty sump, stop at full.
- The scheduler runs every 5 s and starts at most one pump per 3 s (staggered starts), so expect pumps to switch on one after another, not all at once.
- Firmware should still enforce dry-run/overflow protection **locally** even if a `cmd` message never arrives (network drop) — see the "offline safety" note in the project plan.

## REST API (FastAPI backend)

| Endpoint | Method | Returns |
|---|---|---|
| `/health` | GET | `{"status": "ok"}` |
| `/tanks` | GET | Latest telemetry per tank |
| `/feeder/soc?feeder_id=feeder-1` | GET | `{feeder_id, soc_kwh, soc_pct_of_max, tanks_reporting, pumps_running, sheddable_w, pause_minutes_available}` |
| `/forecast?horizons=0,15,30,60` | GET | List of `{horizon_min, solar_w, feeder_load_w, discom_load_mw, solar_source, load_source}` |
| `/sources` | GET | Live feed health, which models are active, their held-out accuracy |
| `/loadcurve` | GET | Today's feeder in 5-min averages: `[{ts, pump_w, solar_w, feeder_load_w}]` |
| `/commands` | GET | Last 200 pump-command *changes* (building_id, action, reason, ts) |
| `/impact` | GET | Today's counters: `wh_pumped, green_share_pct, wh_evening_peak, tod_saving_inr, pause_events, pause_minutes, max_shed_w, tariff` |
| `/resident/{id}` | GET | `{level_pct, litres, sump_level_pct, pump, next_pump{at, why}, next_supply, alerts[], savings, tariff}` — alerts include low water, possible leak, dry sump, full, pause |
| `/pause` | GET / POST | GET `{"active": bool}` (persists across restarts). POST body `{"active": true/false}` — publishes `vtb/discom/pause`. A pause sheds every pump except tanks already below the safe minimum |
| `/demo` | GET | `{mock_running, cloud, leaks}` — demo controls only work with the in-process mock |
| `/demo/cloud` | POST | `{"active": bool}` — simulate covering the solar panel |
| `/demo/leak` | POST | `{"building_id": "tank-03", "active": bool}` — make a mock tank drain like a leak |
| `/simulate?n_buildings=300&cloudy_day=false` | GET | `{n_buildings, peak_reduction_pct, kwh_shifted, evening_pumping_cut_pct, metrics{baseline,rules,optimal}, inputs, curve[]}`. Curve points (W, every 5 min): pump load `baseline_w` / `optimized_w` / `optimal_w`, plus `base_load_w`, `solar_w` and feeder net load `net_*_w` |
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
