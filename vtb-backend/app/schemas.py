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


class FeederSoC(BaseModel):
    feeder_id: str
    soc_kwh: float                # kWh of pumping that can be shifted right now
    soc_pct_of_max: float
    tanks_reporting: int


class LoadCurvePoint(BaseModel):
    t_min: int                    # minutes from simulation start
    baseline_w: float             # load with no smart scheduling
    optimized_w: float            # load with VTB scheduling


class SimulationResult(BaseModel):
    n_buildings: int
    peak_reduction_pct: float
    kwh_shifted: float
    curve: list[LoadCurvePoint]


class PauseRequest(BaseModel):
    active: bool
