"""
Central config. Tune thresholds here instead of hunting through the codebase.
"""

# --- Tank / safety ---
SAFE_MIN_LEVEL_PCT = 15.0        # never let a tank drop below this
OVERFLOW_LEVEL_PCT = 95.0        # stop filling above this
TANK_CAPACITY_LITRES = 1000.0    # per-tank capacity used in SoC math
ENERGY_PER_LITRE_WH = 0.5        # Wh of pumping energy represented per litre moved
                                  # (rough: pump power / typical flow rate — tune from hardware team's numbers)

# --- Scheduling ---
STAGGER_DELAY_SEC = 3            # min delay between two pumps starting
SOLAR_SURPLUS_THRESHOLD_W = 150  # above this, treat as "green hour"
FORECAST_DIP_LOOKAHEAD_MIN = 60  # how far ahead we check for a predicted solar dip

# --- Simulation ---
DEFAULT_SIM_BUILDINGS = 300
SIM_TIMESTEP_MIN = 5

# --- Bus / MQTT topics (must match the Day-1 contract with hardware) ---
TOPIC_TANK_TELEMETRY = "vtb/tank/{id}/telemetry"   # ESP32 -> server
TOPIC_SOLAR_TELEMETRY = "vtb/solar/telemetry"      # ESP32 -> server
TOPIC_TANK_CMD = "vtb/tank/{id}/cmd"               # server -> ESP32
TOPIC_DISCOM_PAUSE = "vtb/discom/pause"            # dashboard -> all

# Set to a real broker URL when hardware is ready, e.g. "mqtt://localhost:1883".
# When None, the app runs on the in-memory Bus (app/bus.py) so backend + dashboard
# work end-to-end with zero external dependencies.
MQTT_BROKER_URL = None
