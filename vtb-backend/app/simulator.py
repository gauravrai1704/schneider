"""
Feeder-scale simulation: N buildings over one day, same water demand,
three ways of deciding when pumps run.

  baseline   how it works today: each pump switches on when its tank falls
             below a per-building threshold (25-45%) and runs until full
  rules      the live VTB scheduler (app/scheduler.py), stepped every 5 min
  optimal    day-ahead LP plan (app/optimizer.py) — the best-case benchmark

Everything is in real-world units: 0.75 HP pumps, 1000 L tanks, 5000 L
sumps, CPHEEO water demand, municipal supply windows, real Delhi solar and
load shapes (app/sim_inputs.py). The feeder's net load is household demand
+ pumps - local solar; that is what a DISCOM's peak is measured on.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import numpy as np

from app import config
from app.clock import now_ist, to_ist
from app.headroom import pumps_allowed, valley_ceiling
from app.municipal import in_window
from app.optimizer import Cluster, optimise
from app.scheduler import Scheduler, TankSnapshot
from app.sim_inputs import build_inputs
from app.water import _building_params, daily_litres, draw_litres_per_hr

DT_H = config.SIM_TIMESTEP_MIN / 60
FLOW_L = config.SIM_PUMP_FLOW_LPH * DT_H            # litres one pump moves per step
TANK_L, SUMP_L = config.TANK_CAPACITY_LITRES, config.SUMP_CAPACITY_LITRES
EVENING_PEAK = (18, 23)                              # IST hours, Delhi evening peak
LP_CLUSTERS = 12
WINDOW_HOURS = sum(end - start for start, end in config.MUNICIPAL_SUPPLY_WINDOWS)


@dataclass
class Fleet:
    ids: list[str]
    tank0: np.ndarray        # litres
    sump0: np.ndarray        # litres
    on_below: np.ndarray     # baseline switch-on threshold, % of tank
    demand: np.ndarray       # litres, [building, step]
    inflow: np.ndarray       # litres, [building, step]


def _fleet(n: int, times: list[datetime]) -> Fleet:
    rng = np.random.default_rng(config.SIM_SEED + n)
    ids = [f"sim-{i:04d}" for i in range(n)]
    demand = np.array([[draw_litres_per_hr(t, b) * DT_H for t in times] for b in ids])
    window = np.array([in_window(t) for t in times], dtype=float)
    # Municipal supply delivers ~10% more than daily demand, spread over the windows
    inflow = np.array([daily_litres(b) * 1.1 / WINDOW_HOURS * DT_H * window for b in ids])
    lo, hi = config.SIM_BASELINE_ON_PCT
    return Fleet(
        ids=ids,
        tank0=rng.uniform(0.4, 0.8, n) * TANK_L,
        sump0=rng.uniform(0.3, 0.6, n) * SUMP_L,
        on_below=rng.uniform(lo, hi, n),
        demand=demand, inflow=inflow,
    )


def _step_water(tank, sump, on, demand, inflow):
    """Advance every building one step. Firmware won't pump from a dry sump."""
    sump_min = SUMP_L * config.SUMP_MIN_LEVEL_PCT / 100
    moved = np.where(on, np.minimum.reduce([np.full_like(tank, FLOW_L), TANK_L - tank, np.maximum(sump - sump_min, 0)]), 0.0)
    tank = tank + moved - demand
    unmet = np.maximum(-tank, 0)
    tank = np.maximum(tank, 0)
    sump = sump - moved + inflow
    spill = np.maximum(sump - SUMP_L, 0)
    sump = np.minimum(sump, SUMP_L)
    pumping = moved > 0
    return tank, sump, pumping, unmet, spill


def _run_baseline(f: Fleet, T: int):
    tank, sump, on = f.tank0.copy(), f.sump0.copy(), np.zeros(len(f.ids), bool)
    pumps, low, unmet = np.zeros(T), 0, 0.0
    for t in range(T):
        pct = 100 * tank / TANK_L
        on = np.where(pct < f.on_below, True, np.where(pct >= config.OVERFLOW_LEVEL_PCT, False, on))
        tank, sump, pumping, short, _ = _step_water(tank, sump, on, f.demand[:, t], f.inflow[:, t])
        on &= pumping            # firmware stops a pump that can't move water
        pumps[t] = pumping.sum()
        low += int((100 * tank / TANK_L < config.SAFE_MIN_LEVEL_PCT).sum())
        unmet += short.sum()
    return pumps, low, unmet, tank


def _run_rules(f: Fleet, times: list[datetime], solar_demo_w: np.ndarray, headroom_pumps: np.ndarray):
    sched = Scheduler()
    tank, sump, on = f.tank0.copy(), f.sump0.copy(), np.zeros(len(f.ids), bool)
    T = len(times)
    lookahead = int(config.FORECAST_DIP_LOOKAHEAD_MIN / config.SIM_TIMESTEP_MIN)
    pumps, low, unmet = np.zeros(T), 0, 0.0
    for t, now in enumerate(times):
        # The simulator knows the day's actual solar, so it answers "dip coming?" directly
        future = solar_demo_w[t + lookahead] if t + lookahead < T else 0.0
        dip = future < config.SOLAR_SURPLUS_THRESHOLD_W
        snaps = [TankSnapshot(b, 100 * tank[i] / TANK_L, 100 * sump[i] / SUMP_L, bool(on[i]))
                 for i, b in enumerate(f.ids)]
        decisions = sched.decide(snaps, float(solar_demo_w[t]), now, dip_soon=dip, max_running=int(headroom_pumps[t]))
        on = np.array([d.action == "ON" for d in decisions])
        tank, sump, pumping, short, _ = _step_water(tank, sump, on, f.demand[:, t], f.inflow[:, t])
        on = pumping
        pumps[t] = pumping.sum()
        low += int((100 * tank / TANK_L < config.SAFE_MIN_LEVEL_PCT).sum())
        unmet += short.sum()
    return pumps, low, unmet, tank


def _run_optimal(f: Fleet, base_kw, solar_kw, green):
    # Cluster buildings by when they use water, so each cluster's demand stays peaky like reality
    phase = np.array([_building_params(b)[0] for b in f.ids])
    groups = np.array_split(np.argsort(phase), min(LP_CLUSTERS, len(f.ids)))
    clusters = [
        Cluster(
            n=len(g),
            tank_init_l=float(f.tank0[g].sum()),
            tank_min_l=len(g) * TANK_L * (config.SAFE_MIN_LEVEL_PCT + 10) / 100,   # buffer: clusters hide spread
            tank_max_l=len(g) * TANK_L * config.OVERFLOW_LEVEL_PCT / 100,
            sump_init_l=float(f.sump0[g].sum()),
            sump_min_l=len(g) * SUMP_L * config.SUMP_MIN_LEVEL_PCT / 100,
            sump_max_l=len(g) * SUMP_L,
            demand_l=f.demand[g].sum(axis=0),
            inflow_l=f.inflow[g].sum(axis=0),
        )
        for g in groups if len(g)
    ]
    starts_per_step = config.SIM_TIMESTEP_MIN * 60 / config.STAGGER_DELAY_SEC
    return optimise(clusters, base_kw, solar_kw, config.SIM_PUMP_KW, FLOW_L, starts_per_step, green)


def _metrics(pumps_on, base_kw, solar_kw, green, evening, low, unmet, n, T, start_tank=None, end_tank=None):
    pump_kw = pumps_on * config.SIM_PUMP_KW
    net = base_kw + pump_kw - solar_kw
    kwh = pump_kw * DT_H
    return {
        "pump_kwh": round(float(kwh.sum()), 1),
        "pump_kwh_outside_green": round(float(kwh[~green].sum()), 1),
        "green_share_pct": round(100 * float(kwh[green].sum()) / max(float(kwh.sum()), 1e-9), 1),
        "evening_peak_pump_kwh": round(float(kwh[evening].sum()), 1),
        "pump_peak_kw": round(float(pump_kw.max()), 1),
        "net_peak_kw": round(float(net.max()), 1),
        "pct_time_below_safe_min": round(100 * low / (n * T), 2) if low is not None else None,
        "unmet_water_litres": round(float(unmet), 1) if unmet is not None else None,
        # stored water carried into tomorrow; extra pumping vs baseline is mostly this
        "tank_fill_start_pct": round(100 * float(start_tank.sum()) / (n * TANK_L), 1) if start_tank is not None else None,
        "tank_fill_end_pct": round(100 * float(end_tank.sum()) / (n * TANK_L), 1) if end_tank is not None else None,
    }


@lru_cache(maxsize=16)
def _simulate(n_buildings: int, day_iso: str, cloudy_day: bool, with_optimal: bool) -> dict:
    day = datetime.fromisoformat(day_iso)
    inp = build_inputs(day, cloudy_day)
    times, T = inp.times, len(inp.times)
    base_kw = inp.load_shape * config.SIM_HOUSEHOLD_PEAK_KW * n_buildings
    solar_kw = inp.ghi / 1000 * config.SIM_SOLAR_KWP_PER_BUILDING * n_buildings
    solar_demo_w = inp.ghi / 1000 * config.SOLAR_PEAK_W          # what the scheduler's thresholds expect
    green = solar_demo_w >= config.SOLAR_SURPLUS_THRESHOLD_W
    evening = np.array([EVENING_PEAK[0] <= t.hour < EVENING_PEAK[1] for t in times])

    fleet = _fleet(n_buildings, times)

    # Headroom: valley-fill solar hours up to the lowest ceiling that fits the day's pumping;
    # outside them, never above the day's peak. The simulator knows the day's real profile;
    # live, the same calculation runs on the 6 h load + solar forecast.
    net_wo_pumps = base_kw - solar_kw
    need_l = fleet.demand.sum() + np.clip(0.9 * TANK_L - fleet.tank0, 0, None).sum()
    ceiling = valley_ceiling(net_wo_pumps, green, config.SIM_PUMP_KW, need_l / config.SIM_PUMP_FLOW_LPH, DT_H)
    headroom_pumps = np.array([
        pumps_allowed(net_wo_pumps[t], ceiling if green[t] else net_wo_pumps.max(), config.SIM_PUMP_KW)
        for t in range(T)
    ])
    base_pumps, base_low, base_unmet, base_end = _run_baseline(fleet, T)
    rule_pumps, rule_low, rule_unmet, rule_end = _run_rules(fleet, times, solar_demo_w, headroom_pumps)
    opt = _run_optimal(fleet, base_kw, solar_kw, green) if with_optimal else {"status": "skipped", "pumps_on": None}
    opt_pumps = opt["pumps_on"]

    m_base = _metrics(base_pumps, base_kw, solar_kw, green, evening, base_low, base_unmet, n_buildings, T,
                      fleet.tank0, base_end)
    m_rule = _metrics(rule_pumps, base_kw, solar_kw, green, evening, rule_low, rule_unmet, n_buildings, T,
                      fleet.tank0, rule_end)
    m_opt = _metrics(opt_pumps, base_kw, solar_kw, green, evening, None, None, n_buildings, T) if opt_pumps is not None else None

    def pct_cut(a, b):
        return round(100 * (a - b) / a, 1) if a > 0 else 0.0

    curve = []
    for t in range(T):
        point = {
            "t_min": t * config.SIM_TIMESTEP_MIN,
            "baseline_w": round(base_pumps[t] * config.SIM_PUMP_KW * 1000, 1),
            "optimized_w": round(rule_pumps[t] * config.SIM_PUMP_KW * 1000, 1),
            "base_load_w": round(base_kw[t] * 1000, 1),
            "solar_w": round(solar_kw[t] * 1000, 1),
            "net_baseline_w": round((base_kw[t] + base_pumps[t] * config.SIM_PUMP_KW - solar_kw[t]) * 1000, 1),
            "net_optimized_w": round((base_kw[t] + rule_pumps[t] * config.SIM_PUMP_KW - solar_kw[t]) * 1000, 1),
        }
        if opt_pumps is not None:
            point["optimal_w"] = round(opt_pumps[t] * config.SIM_PUMP_KW * 1000, 1)
            point["net_optimal_w"] = round((base_kw[t] + opt_pumps[t] * config.SIM_PUMP_KW - solar_kw[t]) * 1000, 1)
        curve.append(point)

    return {
        "n_buildings": n_buildings,
        "peak_reduction_pct": pct_cut(m_base["net_peak_kw"], m_rule["net_peak_kw"]),
        "kwh_shifted": round(max(m_base["pump_kwh_outside_green"] - m_rule["pump_kwh_outside_green"], 0.0), 1),
        "evening_pumping_cut_pct": pct_cut(m_base["evening_peak_pump_kwh"], m_rule["evening_peak_pump_kwh"]),
        "metrics": {"baseline": m_base, "rules": m_rule, "optimal": m_opt},
        "optimizer_status": opt["status"],
        "inputs": {
            "date": day.date().isoformat(), "solar": inp.solar_source, "load": inp.load_source,
            "pump_kw": config.SIM_PUMP_KW, "household_peak_kw": config.SIM_HOUSEHOLD_PEAK_KW,
            "solar_kwp_per_building": config.SIM_SOLAR_KWP_PER_BUILDING,
            "water": f"{config.WATER_LPCD:.0f} L/person/day x {config.PERSONS_PER_BUILDING} persons (CPHEEO)",
            "supply_windows": [f"{a:02d}:00-{b:02d}:00" for a, b in config.MUNICIPAL_SUPPLY_WINDOWS],
        },
        "curve": curve,
    }


def run_simulation(n_buildings: int, day: datetime | None = None, cloudy_day: bool = False,
                   with_optimal: bool = True) -> dict:
    day = to_ist(day) if day else now_ist()
    day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return _simulate(n_buildings, day.isoformat(), cloudy_day, with_optimal)
