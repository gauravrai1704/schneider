"""
Resident alerts, including leak detection.

Leak rule: while the pump is idle, the tank should only drop as fast as the
household uses water. If it falls much faster than the demand model allows
for long enough, something is draining it — a leak, a tap left open, or a
faulty float valve.
"""
from __future__ import annotations
import time
from collections import deque
from datetime import datetime

from app import config
from app.water import draw_litres_per_hr


class LeakDetector:
    def __init__(self):
        self._hist: dict[str, deque] = {}

    @staticmethod
    def window_sec() -> float:
        return max(60.0, config.LEAK_WINDOW_SEC / config.TELEMETRY_TIME_SCALE)

    def observe(self, building_id: str, level_pct: float, pump_on: bool, now: datetime, mono: float | None = None):
        mono = time.monotonic() if mono is None else mono
        h = self._hist.setdefault(building_id, deque())
        h.append((mono, now, level_pct, pump_on))
        keep = self.window_sec() * 1.5
        while h and mono - h[0][0] > keep:
            h.popleft()

    def check(self, building_id: str) -> dict | None:
        h = self._hist.get(building_id)
        if not h:
            return None
        window = self.window_sec()
        end = h[-1][0]
        recent = [e for e in h if end - e[0] <= window]
        if end - recent[0][0] < 0.9 * window or any(e[3] for e in recent):
            return None                          # not enough idle-pump history yet
        drop_pct = recent[0][2] - recent[-1][2]
        if drop_pct <= 0:
            return None
        sim_hours = (end - recent[0][0]) * config.TELEMETRY_TIME_SCALE / 3600
        observed = drop_pct / 100 * config.TANK_CAPACITY_LITRES / sim_hours
        expected = max(draw_litres_per_hr(e[1], building_id) for e in (recent[0], recent[len(recent) // 2], recent[-1]))
        if observed > expected * config.LEAK_EXCESS_RATIO + config.LEAK_MIN_EXCESS_LPH:
            return {"observed_lph": round(observed), "expected_lph": round(expected)}
        return None


def resident_alerts(tank: dict, leak: dict | None, paused: bool, next_supply: datetime) -> list[dict]:
    alerts = []
    level, sump = tank["level_pct"], tank.get("sump_level_pct")
    if level < config.SAFE_MIN_LEVEL_PCT:
        alerts.append({"code": "low", "tone": "critical", "title": "Water running low",
                       "text": "Your tank is below the safe level. A refill gets top priority, whatever the grid is doing."})
    if leak:
        alerts.append({"code": "leak", "tone": "critical", "title": "Possible leak",
                       "text": f"Your tank is draining at about {leak['observed_lph']} L/h with the pump off — "
                               f"normal use right now is about {leak['expected_lph']} L/h. Check taps, pipes and the float valve."})
    if sump is not None and sump <= config.SUMP_MIN_LEVEL_PCT:
        alerts.append({"code": "dry_run", "tone": "warning", "title": "Sump nearly empty",
                       "text": f"The pump is stopped to protect the motor. Municipal supply should refill it at {next_supply:%H:%M}."})
    if level >= config.OVERFLOW_LEVEL_PCT:
        alerts.append({"code": "full", "tone": "good", "title": "Tank full",
                       "text": "The pump stopped automatically to prevent overflow."})
    if paused:
        alerts.append({"code": "paused", "tone": "warning", "title": "Grid support in progress",
                       "text": "Pumping is briefly paused to help the local grid. Your water stays above the safe level."})
    return alerts
