# Virtual Tank Battery

**Turning India's rooftop water tanks into a neighbourhood-scale battery for renewable intermittency.**
Schneider Electric hackathon · Challenge 03: Grid Reliability

> *"India already owns millions of batteries. They're on its rooftops, filled with water."*

---

## The idea

- India is adding solar and wind fast, but their output dips with clouds and evenings. When supply drops, weak urban and peri-urban feeders see outages first.
- Grid-scale batteries are expensive and slow to reach those areas. DISCOMs need **cheap, local flexibility** at the feeder level.
- Almost every Indian building already has a **ground sump, a pump and an overhead tank**. Pumping is a large but flexible load: it doesn't matter *when* water is pumped, as long as the tank never runs dry.
- So empty tank space acts like stored energy. **Pump during solar surplus, pause during dips.** Thousands of tanks together form a virtual battery the grid already owns.

## How it works

```mermaid
flowchart LR
    A[Tank + sump sensors<br/>pump relay · ESP32] <-->|MQTT| B[Backend · FastAPI]
    B --> C[ML forecaster<br/>solar + feeder load]
    B --> D[Scheduler<br/>safety · stagger · pause]
    B --> E[Feeder simulator]
    B <-->|REST + WebSocket| F[Dashboard<br/>DISCOM · Resident · Simulation]
    G[(Open-Meteo<br/>NASA POWER<br/>Delhi SLDC)] --> C
```

- **Retrofit controller** (₹500–800): senses tank level, sump level and pump power, and switches the existing pump through a relay. It protects the pump locally even if the internet drops.
- **Forecasting:** LightGBM models trained on a year of real Delhi data predict solar output and feeder load 15 minutes to 6 hours ahead.
- **Scheduler:** pumps in green hours, pre-fills before forecast dips, never lets a tank fall below a safe level, protects the pump from running dry, and staggers motor starts to avoid voltage dips.
- **DISCOM dashboard:** live State of Charge (kWh of shiftable pumping), forecasts, and a one-tap **Pump Pause** for demand response.
- **Resident view:** tank level, pump status in plain language, and dry-run and overflow alerts.

## Repository layout

| Folder | What's inside |
|---|---|
| [`vtb-backend/`](vtb-backend/) | FastAPI server, MQTT bus, ML forecasting, scheduler, simulator, data pipelines, tests |
| [`vtb-frontend/`](vtb-frontend/) | React + Tailwind + Recharts dashboard (light/dark themes, mobile-friendly) |

## Quick start

You need Python 3.11+ and Node 18+. No broker, database server or API keys are required; mock telemetry runs automatically.

**Backend** (Windows PowerShell; on macOS/Linux use `source .venv/bin/activate`):

```powershell
cd vtb-backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

**Dashboard** (in a second terminal):

```powershell
cd vtb-frontend
npm install
npm run dev
```

Dashboard: http://localhost:5173

**Tests:** `cd vtb-backend` and then `python -m pytest -q`

To connect real ESP32s, start the backend with `VTB_MQTT_URL=mqtt://<broker>:1883`; the mock switches itself off. The MQTT and REST contract is in [`vtb-backend/docs/api_contract.md`](vtb-backend/docs/api_contract.md).

## Data: what's real

| Data | Source | |
|---|---|---|
| Solar irradiance (training) | [NASA POWER](https://power.larc.nasa.gov) hourly, Delhi | ✅ Real |
| Weather forecasts (training + live) | [Open-Meteo](https://open-meteo.com) archived + live forecasts | ✅ Real |
| Feeder load (training + live) | [Delhi SLDC](https://www.delhisldc.org) 5-min DISCOM load (BYPL) | ✅ Real |
| Building water demand | CPHEEO norm of 135 L/person/day, Indian daily usage pattern | ⚠️ Synthetic |
| Tank telemetry | In-process mock until the hardware is connected | ⚠️ Mock |

The full list is in [`vtb-backend/data/SOURCES.md`](vtb-backend/data/SOURCES.md).

**Forecast accuracy** (held-out weeks across all seasons):

| Forecast | Our model | Best simple baseline |
|---|---|---|
| Solar, 1–6 h ahead | **45.9 W/m²** error | 70.6 (raw weather forecast) |
| Feeder load, 15 min – 6 h ahead | **5.8%** error | 7.1% (same time yesterday) |

## Status

- [x] Hardware/software interface contract (MQTT + REST)
- [x] Backend: IST-correct scheduling, MQTT bridge, sump-based dry-run protection
- [x] Forecasting on real Delhi data with live feeds and offline fallbacks
- [x] Dashboard: DISCOM, Resident and Simulation views
- [ ] Scheduler v2: fixed tick, municipal supply sync, per-feeder SoC
- [ ] Simulator: realistic baseline and PuLP optimiser. **Current simulator numbers are a preview; don't quote them.**
- [ ] Impact, resident savings (₹) and demo-control endpoints
- [ ] Physical model integration (ESP32, pumps, sensors)

## Team

| Role | Owner |
|---|---|
| Hardware & firmware | _add name_ |
| Backend, ML & scheduling | Abhiraj Agarwal |
| Dashboard & demo | _add name_ |
