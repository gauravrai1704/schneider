# Virtual Tank Battery — Backend

Intelligence layer for the Virtual Tank Battery project: forecasting,
rule-based scheduler, feeder-scale simulator, and the REST/WebSocket API the
dashboard consumes.

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
python3 -m app.train_forecast   # trains the LightGBM forecast models (~10s)
uvicorn app.main:app --reload --port 8000
```

The training step is optional — if you skip it, `forecast.py` automatically
falls back to the physics-based heuristic curves, so the app still runs
fully. With trained models present, `/forecast` uses LightGBM predictions
instead.

No broker, no external services needed either way. A mock telemetry
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
  database.py     SQLite via SQLAlchemy
  models.py       DB tables
  schemas.py      API response shapes
  data_gen.py     synthetic historical data (solar cloud cover, feeder load) for training
  train_forecast.py  trains + saves the LightGBM forecast models
  forecast.py     solar / feeder-load / water-use forecasting (ML-backed, heuristic fallback)
  scheduler.py    rule-based pump ON/OFF decisions + safety + stagger
  simulator.py    N-building feeder simulation for the "scales to a city" demo
  main.py         FastAPI app — wires everything together
  models_store/   trained model files (.joblib), created by train_forecast.py
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

## What's real vs mocked today

| Piece | Status |
|---|---|
| Scheduler logic (safety, staggering, pause override, dip pre-fill) | Real |
| SoC calculation | Real |
| Feeder-scale simulator (300 buildings, before/after curves) | Real |
| Forecasting | Real ML (LightGBM) trained on synthetic history, heuristic fallback if untrained |
| Telemetry source | Mocked in-process — swap per `docs/api_contract.md` once ESP32s are ready |

## Suggested next steps

1. Point the dashboard at `http://localhost:8000` and `/ws/live` — everything above is already live with mock data.
2. When the hardware teammate has telemetry flowing, follow the "switch to real hardware" section in `docs/api_contract.md`.
3. Once real feeder/solar history exists, replace `data_gen.py`'s synthetic generators with real-data loaders and re-run `train_forecast.py` — the model code itself doesn't change.
4. Consider swapping the rule-based `scheduler.py` for an LP/greedy optimizer (PuLP/OR-Tools) if you want the "optimized" claim to be literal.
