"""
Central config. Tune thresholds here instead of hunting through the codebase.
"""
import os
from datetime import timedelta, timezone

# --- Location / time ---
# India has no DST, so a fixed +05:30 offset is exact and needs no tzdata on Windows.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
CITY = "Delhi"
LATITUDE = 28.61
LONGITUDE = 77.21
# Delhi SLDC column used as "our" feeder's load shape. BYPL (BSES Yamuna) serves
# dense east/central Delhi — the kind of feeder that browns out first.
# Other columns on the SLDC page: DELHI (state total), BRPL, NDPL (TPDDL), NDMC, MES.
LOAD_DISCOM = "BYPL"

# --- Tank / safety ---
SAFE_MIN_LEVEL_PCT = 15.0        # never let a tank drop below this
OVERFLOW_LEVEL_PCT = 95.0        # stop filling above this
SUMP_MIN_LEVEL_PCT = 10.0        # below this the pump would run dry
TANK_CAPACITY_LITRES = 1000.0    # per-tank capacity used in SoC math
ENERGY_PER_LITRE_WH = 0.5        # Wh of pumping energy per litre lifted
                                  # (0.75 HP pump ~560 W fills 1000 L in ~50 min -> ~0.47 Wh/L)

# --- Water demand (CPHEEO Manual on Water Supply: 135 litres per capita per day, urban) ---
WATER_LPCD = 135.0
PERSONS_PER_BUILDING = 5         # Census 2011 avg Indian household ~4.8

# --- Scheduling ---
STAGGER_DELAY_SEC = 3            # min delay between two pumps starting
SOLAR_SURPLUS_THRESHOLD_W = 150  # above this, treat as "green hour"
FORECAST_DIP_LOOKAHEAD_MIN = 60  # how far ahead we check for a predicted solar dip

# --- Demo scaling ---
# Real data drives the *shape* of the solar and load curves; these set the demo
# magnitude so numbers stay comparable with the physical model's dashboard.
SOLAR_PEAK_W = 600.0             # panel output at 1000 W/m² irradiance
FEEDER_PEAK_W = 1200.0           # feeder load at the DISCOM's historical peak

# --- Simulation ---
DEFAULT_SIM_BUILDINGS = 300
SIM_TIMESTEP_MIN = 5

# --- Bus / MQTT topics (must match the Day-1 contract with hardware) ---
TOPIC_TANK_TELEMETRY = "vtb/tank/{id}/telemetry"   # ESP32 -> server
TOPIC_SOLAR_TELEMETRY = "vtb/solar/telemetry"      # ESP32 -> server
TOPIC_TANK_CMD = "vtb/tank/{id}/cmd"               # server -> ESP32
TOPIC_DISCOM_PAUSE = "vtb/discom/pause"            # dashboard -> all

# Set VTB_MQTT_URL to a real broker when hardware is ready, e.g.
# "mqtt://localhost:1883". When unset, the app runs on the in-memory Bus
# (app/bus.py) so backend + dashboard work end-to-end with zero external dependencies.
MQTT_BROKER_URL = os.environ.get("VTB_MQTT_URL") or None

# --- External data (all public, no API key) ---
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
NASA_POWER_HOURLY_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
DELHI_SLDC_LOAD_URL = "https://www.delhisldc.org/Loaddata.aspx"
WEATHER_REFRESH_SEC = 15 * 60
GRID_REFRESH_SEC = 5 * 60
# Training window: NASA POWER hourly lags ~3 months, so a full year ending mid-2026.
TRAIN_START = "2025-07-01"
TRAIN_END = "2026-06-29"
# Set VTB_OFFLINE=1 to skip all live fetches (e.g. no venue wifi); forecasts
# fall back to the last cached data, then to ML-without-weather, then heuristics.
OFFLINE = os.environ.get("VTB_OFFLINE") == "1"
