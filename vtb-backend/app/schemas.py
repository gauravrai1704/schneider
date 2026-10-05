from pydantic import BaseModel, ConfigDict
from datetime import datetime


class TankState(BaseModel):
    building_id: str
    level_pct: float
    pump_on: bool
    pump_w: float
    sump_level_pct: float | None = None
    ts: datetime

    model_config = ConfigDict(from_attributes=True)


class SolarState(BaseModel):
    solar_w: float
    lux: float
    ts: datetime

    model_config = ConfigDict(from_attributes=True)


class ForecastPoint(BaseModel):
    horizon_min: int
    solar_w: float
    feeder_load_w: float
    discom_load_mw: float | None = None   # real DISCOM load behind the scaled feeder figure
    solar_source: str = "heuristic"
    load_source: str = "heuristic"


class FeederSoC(BaseModel):
    feeder_id: str
    soc_kwh: float                # kWh of pumping that can be shifted right now
    soc_pct_of_max: float
    tanks_reporting: int
    pumps_running: int = 0
    sheddable_w: float = 0.0                      # load a Pump Pause removes right now
    pause_minutes_available: float | None = None  # before the first tank hits its safe minimum


class LoadCurvePoint(BaseModel):
    t_min: int                    # minutes from midnight IST
    baseline_w: float             # pump load, today's behaviour
    optimized_w: float            # pump load, VTB live scheduler
    optimal_w: float | None = None        # pump load, day-ahead LP benchmark
    base_load_w: float | None = None      # household (non-pump) demand
    solar_w: float | None = None          # local solar generation
    net_baseline_w: float | None = None   # feeder net load = household + pumps - solar
    net_optimized_w: float | None = None
    net_optimal_w: float | None = None


class SimulationResult(BaseModel):
    n_buildings: int
    peak_reduction_pct: float              # feeder net peak, VTB vs today
    kwh_shifted: float                     # pumping energy moved into solar hours
    evening_pumping_cut_pct: float = 0.0
    metrics: dict = {}                     # per policy: baseline / rules / optimal
    optimizer_status: str = ""
    inputs: dict = {}                      # data sources and assumptions used
    curve: list[LoadCurvePoint]


class PauseRequest(BaseModel):
    active: bool
