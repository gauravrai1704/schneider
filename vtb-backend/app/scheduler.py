"""
Scheduler: decides ON/OFF for every pump at each tick.

Priority order (highest wins):
  1. DISCOM pause override -> everything OFF
  2. Safety: sump nearly empty (dry-run) -> OFF, tank overflow -> OFF
  3. Below safe minimum -> ON until SAFE_MIN + REFILL_BAND (hysteresis), whatever the grid is doing
  4. Solar surplus right now -> ON. If the forecast shows that surplus ending within
     the lookahead (cloud or sunset), these tanks get start priority: pre-fill while it lasts
  5. Municipal supply: sump >= 70% in the hour before a window -> ON, to make room;
     during a window (often the evening peak) only if the sump is >= 90% and would waste water
  6. Otherwise -> OFF (don't pump on grid power during a dip/peak)

What to do (rules 3-7) is a swappable *policy*; safety, pause and staggering
always wrap it. Staggering is driven by the `now` passed in, not the wall
clock, so the same code runs the 5 s live loop and the 5 min simulator:
at most one new start per STAGGER_DELAY_SEC of elapsed time, emptiest tanks
first. Pumps already running never count against the start budget.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from app.config import (
    FORECAST_DIP_LOOKAHEAD_MIN, OVERFLOW_LEVEL_PCT, PRE_WINDOW_MIN, REFILL_BAND_PCT,
    SAFE_MIN_LEVEL_PCT, SOLAR_SURPLUS_THRESHOLD_W, STAGGER_DELAY_SEC, SUMP_MAKE_ROOM_PCT,
    SUMP_MIN_LEVEL_PCT, SUMP_NEAR_FULL_PCT, SUMP_TRANSFER_MAX_TANK_PCT,
)
from app.forecast import is_predicted_dip
from app.municipal import in_window, minutes_until_next_window, next_window_start


@dataclass
class TankSnapshot:
    building_id: str
    level_pct: float
    sump_level_pct: float | None = None   # None = firmware doesn't report a sump sensor
    pump_on: bool = False


@dataclass
class Decision:
    building_id: str
    action: str      # "ON" / "OFF"
    reason: str


@dataclass
class TickContext:
    now: datetime
    solar_w: float
    solar_surplus: bool
    dip_soon: bool             # surplus now, but forecast to end within the lookahead
    window_soon: bool          # within PRE_WINDOW_MIN of the next municipal window
    window_open: bool          # municipal water flowing into sumps right now
    next_window: datetime


@dataclass
class Want:
    on: bool
    reason: str
    priority: int = 9          # lower = served first when start slots are scarce


Policy = Callable[[TankSnapshot, TickContext, "Scheduler"], Want]


def rule_policy(t: TankSnapshot, ctx: TickContext, sched: "Scheduler") -> Want:
    refilling = t.building_id in sched.refilling
    if t.level_pct < SAFE_MIN_LEVEL_PCT or (refilling and t.level_pct < SAFE_MIN_LEVEL_PCT + REFILL_BAND_PCT):
        return Want(True, "below safe minimum — pumping regardless of solar to protect supply", 0)
    if ctx.solar_surplus and ctx.dip_soon:
        return Want(True, "predicted dip within the hour — pre-filling while solar lasts", 1)
    if ctx.solar_surplus:
        return Want(True, f"solar surplus ({ctx.solar_w:.0f}W) — pumping in green hour", 2)
    if t.sump_level_pct is not None and t.level_pct < SUMP_TRANSFER_MAX_TANK_PCT:
        # Supply windows overlap the evening peak, so while water is flowing we only pump
        # when the sump is about to turn it away; beforehand, a fuller sump is enough.
        # Once a transfer is running it continues 10 points lower (hysteresis, no flapping).
        running = t.pump_on or t.building_id in sched.commanded_on
        band = 10.0 if running else 0.0
        if ctx.window_open and t.sump_level_pct >= SUMP_NEAR_FULL_PCT - band:
            return Want(True, "municipal supply on now — sump nearly full, moving water up so none is wasted", 3)
        if ctx.window_soon and t.sump_level_pct >= SUMP_MAKE_ROOM_PCT - band:
            return Want(True, f"municipal supply at {ctx.next_window:%H:%M} — making room in the sump", 3)
    return Want(False, "no surplus and no dip predicted — holding")


class Scheduler:
    def __init__(self, policy: Policy | None = None, stagger_sec: float = STAGGER_DELAY_SEC):
        self.policy = policy or rule_policy
        self.stagger_sec = stagger_sec
        self.discom_paused = False
        self.refilling: set[str] = set()       # tanks in a safety refill (hysteresis)
        self.commanded_on: set[str] = set()    # our last ON commands (telemetry can lag a tick)
        self._last_tick: datetime | None = None
        self._last_start: datetime | None = None

    def set_pause(self, active: bool):
        self.discom_paused = active

    def _start_budget(self, now: datetime) -> int:
        if self._last_start and (now - self._last_start).total_seconds() < self.stagger_sec:
            return 0
        dt = (now - self._last_tick).total_seconds() if self._last_tick else self.stagger_sec
        return max(1, int(dt // self.stagger_sec))

    def decide(
        self,
        tanks: list[TankSnapshot],
        solar_w: float,
        now: datetime,
        cloud_factor: float | None = None,   # panel clearness index; None = unknown
        k_prev: float | None = None,         # panel clearness ~1 h ago, if known
    ) -> list[Decision]:
        budget = self._start_budget(now)
        self._last_tick = now

        if self.discom_paused:
            self.commanded_on.clear()
            return [Decision(t.building_id, "OFF", "DISCOM pause active") for t in tanks]

        mins_to_window = minutes_until_next_window(now)
        surplus = solar_w >= SOLAR_SURPLUS_THRESHOLD_W
        ctx = TickContext(
            now=now, solar_w=solar_w,
            solar_surplus=surplus,
            dip_soon=surplus and is_predicted_dip(
                now, FORECAST_DIP_LOOKAHEAD_MIN, SOLAR_SURPLUS_THRESHOLD_W, cloud_factor, k_prev),
            window_soon=mins_to_window <= PRE_WINDOW_MIN,
            window_open=in_window(now),
            next_window=next_window_start(now),
        )

        decisions: dict[str, Decision] = {}
        starters: list[tuple[int, float, TankSnapshot, Want]] = []
        for t in tanks:
            # Hard safety, never overridden by the policy
            if t.sump_level_pct is not None and t.sump_level_pct <= SUMP_MIN_LEVEL_PCT:
                decisions[t.building_id] = Decision(t.building_id, "OFF", "sump nearly empty — dry-run protection")
                continue
            if t.level_pct >= OVERFLOW_LEVEL_PCT:
                self.refilling.discard(t.building_id)
                decisions[t.building_id] = Decision(t.building_id, "OFF", "tank full — overflow protection")
                continue

            want = self.policy(t, ctx, self)
            if want.priority == 0:
                self.refilling.add(t.building_id)
            else:
                self.refilling.discard(t.building_id)

            if not want.on:
                decisions[t.building_id] = Decision(t.building_id, "OFF", want.reason)
            elif t.pump_on or t.building_id in self.commanded_on:
                decisions[t.building_id] = Decision(t.building_id, "ON", want.reason)
            else:
                starters.append((want.priority, t.level_pct, t, want))

        # New starts: most urgent, then emptiest, first — limited by the stagger budget
        started = 0
        for _, _, t, want in sorted(starters, key=lambda s: (s[0], s[1])):
            if started < budget:
                decisions[t.building_id] = Decision(t.building_id, "ON", want.reason)
                started += 1
            else:
                decisions[t.building_id] = Decision(t.building_id, "OFF", "wants ON but held for staggered start")
        if started:
            self._last_start = now

        result = [decisions[t.building_id] for t in tanks]
        self.commanded_on = {d.building_id for d in result if d.action == "ON"}
        return result
