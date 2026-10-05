# Virtual Tank Battery — Backend

Intelligence layer for the Virtual Tank Battery project: forecasting,
rule-based scheduler, feeder-scale simulator, and the REST/WebSocket API the
dashboard consumes.

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Trained models and the cleaned training data are committed, so this is all
you need. To rebuild them from scratch (real Delhi data, ~5 min):

```bash
python -m etl.fetch_solar      # NASA POWER irradiance
python -m etl.fetch_weather    # Open-Meteo archived forecasts
python -m etl.fetch_load       # Delhi SLDC load (one page per day, cached)
python -m app.train_forecast   # prints held-out accuracy vs baselines
```

Forecasts use live Open-Meteo weather and live Delhi SLDC load when there's
internet, the last cached response when there isn't, and simpler fallbacks
after that. Every `/forecast` point says which path produced it, and
`/sources` shows feed health and model accuracy. See `data/SOURCES.md` for
every dataset and whether it's real or synthetic.

No MQTT broker is needed. A mock telemetry
generator (`mock/mock_generator.py`) runs automatically inside the same
process and publishes realistic fake data for 8 tanks + solar every 2
seconds, so `/tanks`, `/feeder/soc`, `/forecast`, `/loadcurve` and `/ws/live`
all work immediately. Interactive API docs: `http://localhost:8000/docs`.

## Project layout

```
app/
  config.py       thresholds, topics, tunables, location — start here
  clock.py        IST "now" helpers (never use the server's UTC clock for time-of-day logic)
  bus.py          in-memory pub/sub with MQTT wildcards; MqttBus when VTB_MQTT_URL is set
  water.py        per-building water demand (CPHEEO 135 LPCD norm, deterministic)
  municipal.py    municipal supply windows (sump refill times)
  soc.py          feeder State of Charge, sheddable load, safe pause duration
  headroom.py     feeder headroom cap (valley filling under the forecast peak)
  sim_inputs.py   real solar day (NASA POWER) + BYPL load shape for the simulator
  optimizer.py    day-ahead LP benchmark (PuLP + HiGHS)
  state.py        live in-memory state shared by the control loop and routes
  routes.py       impact, load curve, resident, pause and demo endpoints
  impact.py       today's live impact counters + 5-min load samples (persisted)
  alerts.py       resident alerts incl. leak detection
  tariff.py       time-of-day tariff (DERC slab + MoP ToD rules)
  solar_geometry.py  sun position + clear-sky irradiance
  live_data.py    live Open-Meteo + Delhi SLDC feeds (background refresh, disk cache)
  features.py     feature building shared by training and inference
  database.py     SQLite via SQLAlchemy
  models.py       DB tables
  schemas.py      API response shapes
  train_forecast.py  trains + evaluates the LightGBM models on real data
  forecast.py     solar / feeder-load forecasting (ML + live data, layered fallbacks)
  scheduler.py    rule-based pump ON/OFF decisions + safety + stagger
  simulator.py    N-building feeder simulation for the "scales to a city" demo
  main.py         FastAPI app — wires everything together
  models_store/   trained model files (.joblib), created by train_forecast.py
etl/                  download scripts for the training data
data/
  SOURCES.md          what every dataset is, real vs synthetic
  processed/          cleaned training CSVs
mock/
  mock_generator.py   fake ESP32 telemetry, until real hardware is ready
docs/
  api_contract.md     MQTT + REST contract to share with the hardware teammate
tests/                pytest suite (`python -m pytest -q`)
```

## Environment variables

| Var | Effect |
|---|---|
| `VTB_MQTT_URL` | e.g. `mqtt://localhost:1883` — use a real broker instead of the in-memory bus (mock auto-disabled) |
| `VTB_DISABLE_MOCK=1` | don't start the in-process mock telemetry generator |
| `VTB_OFFLINE=1` | never call external APIs (no venue wifi); uses cached data/fallbacks |

## What's real vs mocked today

| Piece | Status |
|---|---|
| Scheduler (5 s tick, safety + hysteresis, staggered starts, pause, dip pre-fill, municipal supply sync) | Real |
| Feeder SoC (fillable kWh limited by sump water, sheddable W, safe pause duration) | Real |
| Feeder simulator: today's behaviour vs VTB controller vs LP optimum, real Delhi solar + load, real-world units | Real |
| Forecasting | LightGBM trained on a year of real Delhi data (NASA POWER, Open-Meteo, SLDC), live inputs |
| Water demand | Synthetic, scaled to the CPHEEO 135 L/person/day norm |
| Resident savings | DERC domestic rate x ToD factors from the Electricity (Rights of Consumers) Amendment Rules 2023; Delhi's exact ToD hours assumed |
| Leak detection, impact counters, persistent pause | Real |
| Telemetry source | Mocked in-process — swap per `docs/api_contract.md` once ESP32s are ready |

## Suggested next steps

1. Point the dashboard at `http://localhost:8000` and `/ws/live` — everything above is already live with mock data.
2. When the hardware teammate has telemetry flowing, follow the "switch to real hardware" section in `docs/api_contract.md`.
