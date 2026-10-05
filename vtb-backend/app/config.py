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
SUMP_CAPACITY_LITRES = 5000.0    # ground sump, typically several times the overhead tank
ENERGY_PER_LITRE_WH = 0.5        # Wh of pumping energy per litre lifted
                                  # (0.75 HP pump ~560 W fills 1000 L in ~50 min -> ~0.47 Wh/L)

# --- Water demand (CPHEEO Manual on Water Supply: 135 litres per capita per day, urban) ---
WATER_LPCD = 135.0
PERSONS_PER_BUILDING = 5         # Census 2011 avg Indian household ~4.8

# --- Municipal water supply (Delhi Jal Board style twice-daily supply, IST hours) ---
# The sump only refills inside these windows; the scheduler plans tank pumping around them.
MUNICIPAL_SUPPLY_WINDOWS = [(5, 7), (18, 20)]
PRE_WINDOW_MIN = 60              # start making room in the sump this long before a window
SUMP_MAKE_ROOM_PCT = 70.0        # ...if the sump is at least this full
SUMP_NEAR_FULL_PCT = 90.0        # during a window, only pump (from grid) if supply would be turned away

# --- Scheduling ---
SCHEDULER_TICK_SEC = 5           # live control loop period
CMD_REFRESH_SEC = 60             # re-send unchanged commands this often (firmware watchdog)
STAGGER_DELAY_SEC = 3            # min delay between two pumps starting
REFILL_BAND_PCT = 10.0           # safety refill continues until SAFE_MIN + this (hysteresis)
SUMP_TRANSFER_MAX_TANK_PCT = 90.0  # pre-window sump->tank transfer stops at this tank level
PUMP_RATED_W = 40.0              # demo pump draw; real retrofit target ~560 W (0.75 HP)
SOLAR_SURPLUS_THRESHOLD_W = 150  # above this, treat as "green hour"
FORECAST_DIP_LOOKAHEAD_MIN = 60  # how far ahead we check for a predicted solar dip

# --- Demo scaling ---
# Real data drives the *shape* of the solar and load curves; these set the demo
# magnitude so numbers stay comparable with the physical model's dashboard.
SOLAR_PEAK_W = 600.0             # panel output at 1000 W/m² irradiance
FEEDER_PEAK_W = 1200.0           # feeder load at the DISCOM's historical peak

# --- Tariff (for resident savings) ---
# Normal rate: DERC domestic slab 401-800 units, FY 2025-26. Time-of-day shape follows the
# minimums in the Electricity (Rights of Consumers) Amendment Rules 2023: solar hours (8 h,
# set by the SERC) at least 20% cheaper, peak at least 1.10x for domestic consumers.
# Delhi's exact ToD windows are an assumption here — adjust once DERC's order is confirmed.
TARIFF_NORMAL_INR_PER_KWH = 6.50
TARIFF_SOLAR_HOURS = (9, 17)
TARIFF_SOLAR_FACTOR = 0.80
TARIFF_PEAK_HOURS = (18, 23)
TARIFF_PEAK_FACTOR = 1.10

# --- Alerts ---
LEAK_WINDOW_SEC = 600            # pump must be idle this long (in real time) before judging a leak
LEAK_MIN_EXCESS_LPH = 30.0       # observed drain must exceed expected use by this much...
LEAK_EXCESS_RATIO = 1.5          # ...and by this factor
# Mock telemetry runs water use faster than real time; the leak check scales its expectations by this.
TELEMETRY_TIME_SCALE = 1.0

# --- Simulation (real-world scale, not demo watts) ---
DEFAULT_SIM_BUILDINGS = 300
SIM_TIMESTEP_MIN = 5
SIM_PUMP_KW = 0.56               # 0.75 HP domestic pump
SIM_PUMP_FLOW_LPH = SIM_PUMP_KW * 1000 / ENERGY_PER_LITRE_WH   # ~1120 L/h, consistent with Wh/L
SIM_HOUSEHOLD_PEAK_KW = 1.0      # per-building non-pump demand at the DISCOM's peak (BYPL ~1 kW/consumer)
SIM_SOLAR_KWP_PER_BUILDING = 0.5 # feeder-level solar per building (rooftop + local plants)
SIM_BASELINE_ON_PCT = (25.0, 45.0)  # today: pump switched on when tank falls below this (per building)
SIM_SEED = 42

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
