# Data sources

Every dataset the backend uses, whether it's real or synthetic, and how to
regenerate it. All sources are public and need no API key.

| Data | Source | Real? | Used for | Regenerate |
|---|---|---|---|---|
| Hourly solar irradiance, Delhi (28.61N, 77.21E), Jul 2025 – Jun 2026 | [NASA POWER](https://power.larc.nasa.gov) hourly API, `ALLSKY_SFC_SW_DWN` (CERES/MERRA-2 satellite-derived) | ✅ Real | Solar model training target | `python -m etl.fetch_solar` |
| Archived weather forecasts (irradiance, cloud cover, temperature, humidity), same window | [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api) | ✅ Real (forecasts as issued, not observations) | Solar + load model features | `python -m etl.fetch_weather` |
| 5-min electricity demand for Delhi and each DISCOM, same window | [Delhi SLDC](https://www.delhisldc.org/Loaddata.aspx) daily load pages | ✅ Real | Load model training (BYPL column) | `python -m etl.fetch_load` |
| Live weather forecast (yesterday → tomorrow) | [Open-Meteo Forecast API](https://open-meteo.com/en/docs) | ✅ Real, live | Solar + load forecast inputs, mock panel output | automatic, every 15 min |
| Live Delhi load (today, yesterday, a week ago) | Delhi SLDC load page | ✅ Real, live (~15 min delay) | Load forecast lag features | automatic, every 5 min |
| Clear-sky irradiance | Computed: NOAA solar position + Haurwitz clear-sky model | Physics | Normalising solar to a clearness index | — |
| Building water use | Synthetic, scaled to CPHEEO norm (135 L/person/day) × 5 persons, Indian morning/evening peak shape | ⚠️ Synthetic | Mock telemetry, simulator | `app/water.py` |
| Indian public holidays | `holidays` Python package | ✅ Real | Load model feature | — |
| Tank / sump telemetry | `mock/mock_generator.py` until ESP32s are online | ⚠️ Mocked | Everything live | — |

## Files

- `processed/` — cleaned CSVs used for training (committed, so models can be retrained offline).
- `raw/`, `cache/` — per-day SLDC pages and the last live API responses (git-ignored; re-fetchable).

## Scaling

The real data sets the *shape* of the solar and load curves. Demo magnitudes come from
`SOLAR_PEAK_W` and `FEEDER_PEAK_W` in `app/config.py`. `/forecast` also returns the
unscaled `discom_load_mw`, so the real figure is always available.

## Model accuracy (held-out weeks, see `app/models_store/metadata.json`)

| Forecast | ML | Best baseline |
|---|---|---|
| Solar, 1–6 h ahead (with live panel reading) | **45.9 W/m² MAE** | 70.6 raw Open-Meteo · 72.2 persistence |
| Solar, 1 h ahead | **31.0** | 34.1 persistence |
| BYPL load, 15 min – 6 h ahead (with live SLDC) | **5.8% MAPE** (51.9 MW MAE) | 7.1% same-time-yesterday |
| BYPL load, no live SLDC (calendar + weather only) | 8.1% MAPE | — |
