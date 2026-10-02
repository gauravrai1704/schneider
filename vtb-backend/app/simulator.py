"""
Simulates N virtual buildings across a day to produce the "scales to a
neighbourhood" story: baseline (uncoordinated pumping) vs optimized
(VTB scheduling) load curves, peak reduction and kWh shifted.
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta

from app.clock import now_ist, to_ist
from app.config import SIM_TIMESTEP_MIN, TANK_CAPACITY_LITRES
from app.forecast import clear_sky_w
from app.water import draw_litres_per_hr
from app.scheduler import Scheduler, TankSnapshot


def _building_ids(n: int) -> list[str]:
    return [f"sim-{i:04d}" for i in range(n)]


def run_simulation(n_buildings: int, day: datetime | None = None, cloudy_day: bool = False) -> dict:
    day = to_ist(day) if day else now_ist()
    day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    ids = _building_ids(n_buildings)
    levels = {bid: random.uniform(30, 70) for bid in ids}
    scheduler = Scheduler()

    curve = []
    kwh_shifted = 0.0
    pump_w_each = 40.0  # typical small pump draw, matches hardware's 5V mini pump order of magnitude

    steps = int(24 * 60 / SIM_TIMESTEP_MIN)
    for step in range(steps):
        t = day + timedelta(minutes=step * SIM_TIMESTEP_MIN)
        hour_float = t.hour + t.minute / 60
        cloud_factor = 0.3 if (cloudy_day and 10 <= hour_float <= 15) else 1.0
        solar_w = clear_sky_w(t) * cloud_factor

        tanks = [TankSnapshot(bid, levels[bid]) for bid in ids]
        decisions = scheduler.decide(tanks, solar_w, t, cloud_factor)

        n_on = 0
        for d in decisions:
            draw_l = draw_litres_per_hr(t, d.building_id) * (SIM_TIMESTEP_MIN / 60)
            levels[d.building_id] = max(0.0, levels[d.building_id] - 100 * draw_l / TANK_CAPACITY_LITRES)
            if d.action == "ON":
                n_on += 1
                fill_rate_pct_per_tick = 3.0
                levels[d.building_id] = min(100.0, levels[d.building_id] + fill_rate_pct_per_tick)
                kwh_shifted += (pump_w_each * SIM_TIMESTEP_MIN / 60) / 1000

        optimized_w = n_on * pump_w_each
        # Baseline: uncoordinated pumping assumed roughly proportional to water
        # demand at that hour, spread evenly rather than clustered into green hours.
        baseline_fraction_on = 0.15 + 0.10 * (
            1 if (7 <= hour_float <= 9 or 19 <= hour_float <= 21) else 0
        )
        baseline_w = n_buildings * baseline_fraction_on * pump_w_each

        curve.append({"t_min": step * SIM_TIMESTEP_MIN, "baseline_w": round(baseline_w, 1),
                      "optimized_w": round(optimized_w, 1)})

    peak_baseline = max(p["baseline_w"] for p in curve) or 1
    peak_optimized = max(p["optimized_w"] for p in curve)
    peak_reduction_pct = round(100 * (peak_baseline - peak_optimized) / peak_baseline, 1)

    return {
        "n_buildings": n_buildings,
        "peak_reduction_pct": max(peak_reduction_pct, 0.0),
        "kwh_shifted": round(kwh_shifted, 2),
        "curve": curve,
    }
