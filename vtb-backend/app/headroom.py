"""
Feeder headroom: how many pumps may run right now.

Capping pumps under the day's peak stops VTB from *creating* a new peak, but
on its own it still lets every pump start the moment solar appears, piling
load right up to that ceiling. Valley filling sets a lower ceiling instead:
the lowest net-load level that still leaves enough room, across the green
(solar) hours ahead, for the pumping the tanks actually need.

    pumps allowed at step t = floor((ceiling - net_load_t) / pump_w)

where net_load = feeder demand - solar (without the pumps we schedule).
Used by the live loop (6 h forecast) and the simulator (the day's profile).
"""
from __future__ import annotations

import numpy as np

SAFETY_MARGIN = 1.25   # plan room for 25% more pumping than strictly needed


def valley_ceiling(net: np.ndarray, green: np.ndarray, pump_w: float, pump_hours_needed: float,
                   step_h: float) -> float:
    """Lowest ceiling (never above the horizon's peak) that fits the needed pump-hours into green steps."""
    peak = float(net.max())
    if not green.any() or pump_hours_needed <= 0:
        return peak
    need = pump_hours_needed * SAFETY_MARGIN
    lo, hi = float(net[green].min()), peak
    if np.clip((hi - net[green]) / pump_w, 0, None).sum() * step_h < need:
        return peak                                    # can't fit under the peak: use all the room there is
    for _ in range(40):
        mid = (lo + hi) / 2
        room = np.clip((mid - net[green]) / pump_w, 0, None).sum() * step_h
        lo, hi = (mid, hi) if room < need else (lo, mid)
    return hi


def pumps_allowed(net_now: float, ceiling: float, pump_w: float) -> int:
    return int(max(0.0, ceiling - net_now) // pump_w)
