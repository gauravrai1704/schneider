"""
Scheduler: decides ON/OFF for every pump at each tick.

Priority order (highest wins):
  1. DISCOM pause override -> everything OFF
  2. Safety: sump/tank dry -> OFF, tank overflow -> OFF
  3. Predicted dip incoming -> pre-fill now if not already high
  4. Solar surplus right now -> ON
  5. Otherwise -> OFF (don't pump on grid power during a dip/peak)

Staggering: pumps aren't all flipped ON in the same tick — each building
gets an assigned stagger slot so starts spread out and avoid a voltage dip.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import time

from app.config import (
    SAFE_MIN_LEVEL_PCT, OVERFLOW_LEVEL_PCT, SOLAR_SURPLUS_THRESHOLD_W,
    FORECAST_DIP_LOOKAHEAD_MIN, STAGGER_DELAY_SEC,
)
from app.forecast import is_predicted_dip


@dataclass
class TankSnapshot:
    building_id: str
    level_pct: float


@dataclass
class Decision:
    building_id: str
    action: str      # "ON" / "OFF"
    reason: str


class Scheduler:
    def __init__(self):
        self.discom_paused = False
        self._last_start_time: dict[str, float] = {}

    def set_pause(self, active: bool):
        self.discom_paused = active

    def decide(
        self,
        tanks: list[TankSnapshot],
        solar_w: float,
        now: datetime,
        cloud_factor: float = 1.0,
    ) -> list[Decision]:
        decisions: list[Decision] = []

        if self.discom_paused:
            return [Decision(t.building_id, "OFF", "DISCOM pause active") for t in tanks]

        dip_soon = is_predicted_dip(now, FORECAST_DIP_LOOKAHEAD_MIN, SOLAR_SURPLUS_THRESHOLD_W, cloud_factor)
        solar_surplus_now = solar_w >= SOLAR_SURPLUS_THRESHOLD_W

        # Sort by fullest level ascending -> emptiest tanks get priority for stagger slots
        ordered = sorted(tanks, key=lambda t: t.level_pct)

        for i, t in enumerate(ordered):
            if t.level_pct <= 0:
                decisions.append(Decision(t.building_id, "OFF", "sump/tank empty — dry-run protection"))
                continue
            if t.level_pct >= OVERFLOW_LEVEL_PCT:
                decisions.append(Decision(t.building_id, "OFF", "tank full — overflow protection"))
                continue

            wants_on = False
            reason = "no surplus and no dip predicted — holding"

            if solar_surplus_now:
                wants_on = True
                reason = f"solar surplus ({solar_w:.0f}W) — pumping in green hour"
            elif dip_soon and t.level_pct < 70:
                wants_on = True
                reason = "predicted dip within lookahead window — pre-filling now"
            elif t.level_pct < SAFE_MIN_LEVEL_PCT:
                wants_on = True
                reason = "below safe minimum — pumping regardless of solar to protect supply"

            if wants_on and self._stagger_allows(t.building_id, i):
                decisions.append(Decision(t.building_id, "ON", reason))
            elif wants_on:
                decisions.append(Decision(t.building_id, "OFF", "wants ON but held for staggered start"))
            else:
                decisions.append(Decision(t.building_id, "OFF", reason))

        return decisions

    def _stagger_allows(self, building_id: str, slot_index: int) -> bool:
        now_t = time.monotonic()
        min_gap = slot_index * STAGGER_DELAY_SEC
        last = self._last_start_time.get("__last_global_start__", 0)
        if now_t - last < STAGGER_DELAY_SEC and slot_index > 0:
            return False
        self._last_start_time["__last_global_start__"] = now_t
        self._last_start_time[building_id] = now_t
        return True
