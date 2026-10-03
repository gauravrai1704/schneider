"""
Day-ahead pumping plan as a linear program (PuLP + HiGHS) — the best-case
benchmark the live rule-based scheduler is measured against.

Buildings are grouped into clusters with similar water-use timing; each
cluster's decision is how many of its pumps run in each step (continuous,
0..n). That keeps the LP at a few thousand variables, solvable in about a
second, while feeder-level load — what the DISCOM sees — stays exact.

    minimise   peak net feeder load
             + 0.5 x peak net load during solar hours (spreads pumping across the valley)
             + small weight x pumping energy in high-net-load steps (prefer valleys / solar)
             + small weight x municipal water spilled from full sumps
    subject to, per cluster and step:
      tank:  L[t+1] = L[t] + flow*pumps[t] - demand[t],   safe_min <= L <= 95% full
      sump:  S[t+1] = S[t] - flow*pumps[t] + inflow[t] - spill[t],   dry_min <= S <= capacity
      0 <= pumps[t] <= n_buildings,   tanks end the day at least as full as they started
    and feeder-wide: new pump starts per step <= what staggered starts allow
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pulp

ENERGY_WEIGHT = 0.02   # per kWh, scaled by how stressed the feeder is at that step
SPILL_WEIGHT = 0.001   # per litre of municipal water turned away


@dataclass
class Cluster:
    n: int
    tank_init_l: float
    tank_min_l: float
    tank_max_l: float
    sump_init_l: float
    sump_min_l: float
    sump_max_l: float
    demand_l: np.ndarray       # per step
    inflow_l: np.ndarray       # per step


def optimise(clusters: list[Cluster], base_kw: np.ndarray, solar_kw: np.ndarray, pump_kw: float,
             flow_l_per_step: float, max_starts_per_step: float, green: np.ndarray | None = None,
             time_limit_s: float = 20) -> dict:
    T = len(base_kw)
    K = range(len(clusters))
    steps = range(T)
    net_base = base_kw - solar_kw
    stress = np.clip(net_base, 0, None) / max(np.clip(net_base, 0, None).max(), 1e-9)

    prob = pulp.LpProblem("vtb_day_ahead", pulp.LpMinimize)
    p = {(k, t): pulp.LpVariable(f"p_{k}_{t}", lowBound=0, upBound=clusters[k].n) for k in K for t in steps}
    L = {(k, t): pulp.LpVariable(f"L_{k}_{t}", lowBound=clusters[k].tank_min_l, upBound=clusters[k].tank_max_l)
         for k in K for t in range(1, T + 1)}
    S = {(k, t): pulp.LpVariable(f"S_{k}_{t}", lowBound=clusters[k].sump_min_l, upBound=clusters[k].sump_max_l)
         for k in K for t in range(1, T + 1)}
    spill = {(k, t): pulp.LpVariable(f"spill_{k}_{t}", lowBound=0) for k in K for t in steps}
    starts = {(k, t): pulp.LpVariable(f"u_{k}_{t}", lowBound=0) for k in K for t in steps}
    peak = pulp.LpVariable("peak")
    day_peak = pulp.LpVariable("day_peak")

    prob += (
        peak
        + 0.5 * day_peak
        + ENERGY_WEIGHT * pulp.lpSum(stress[t] * pump_kw * p[k, t] for k in K for t in steps)
        + SPILL_WEIGHT * pulp.lpSum(spill.values())
    )

    for k in K:
        c = clusters[k]
        for t in steps:
            prev_L = c.tank_init_l if t == 0 else L[k, t]
            prev_S = c.sump_init_l if t == 0 else S[k, t]
            prob += L[k, t + 1] == prev_L + flow_l_per_step * p[k, t] - float(c.demand_l[t])
            prob += S[k, t + 1] == prev_S - flow_l_per_step * p[k, t] + float(c.inflow_l[t]) - spill[k, t]
            prob += starts[k, t] >= p[k, t] - (p[k, t - 1] if t > 0 else 0)
        prob += L[k, T] >= c.tank_init_l

    for t in steps:
        prob += pulp.lpSum(starts[k, t] for k in K) <= max_starts_per_step
        net_t = float(base_kw[t]) - float(solar_kw[t]) + pump_kw * pulp.lpSum(p[k, t] for k in K)
        prob += net_t <= peak
        if green is not None and green[t]:
            prob += net_t <= day_peak

    solver = pulp.HiGHS(msg=False, timeLimit=time_limit_s)
    if not solver.available():
        solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s)   # bundled with PuLP 2.x/3.x
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        return {"status": pulp.LpStatus[status], "pumps_on": None}
    pumps_on = np.array([sum(p[k, t].value() or 0 for k in K) for t in steps])
    return {"status": "Optimal", "pumps_on": pumps_on}
