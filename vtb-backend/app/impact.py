"""
Live impact counters for today (IST): how much pumping happened, how much of
it ran on solar, how much hit the evening peak, what time-of-day tariffs
saved, and demand-response events. Totals persist in the DB so a restart
mid-demo doesn't zero the counters. Also records 5-minute load samples.

Energy is measured in demo watts (the model's pumps); rupee figures are
scaled to a real 0.75 HP pump so they mean something to a resident.
"""
from __future__ import annotations
from datetime import date, datetime

from app import config, models
from app.clock import to_ist
from app.database import SessionLocal
from app.tariff import factor, period

REAL_SCALE = config.SIM_PUMP_KW * 1000 / config.PUMP_RATED_W   # demo pump watts -> real pump watts
SAMPLE_MIN = 5
FIELDS = ("wh_pumped", "wh_green", "wh_evening", "cost_tod_inr", "cost_flat_inr",
          "pause_events", "pause_seconds", "max_shed_w")


def _blank() -> dict:
    return {f: 0.0 for f in FIELDS}


class ImpactTracker:
    def __init__(self):
        self.day: date | None = None
        self.totals = _blank()
        self.per_building: dict[str, dict] = {}
        self._bucket: datetime | None = None
        self._acc = {"n": 0, "pump_w": 0.0, "solar_w": 0.0, "load_w": 0.0, "load_n": 0}

    def _roll_day(self, today: date):
        if self.day == today:
            return
        self.day, self.totals, self.per_building = today, _blank(), {}
        db = SessionLocal()
        try:
            row = db.get(models.DailyImpact, today)
            if row:
                self.totals = {f: float(getattr(row, f) or 0) for f in FIELDS}
        finally:
            db.close()

    def tick(self, now: datetime, tanks: list[dict], solar_w: float, feeder_load_w: float | None,
             paused: bool, dt_s: float):
        now = to_ist(now)
        self._roll_day(now.date())
        green = solar_w >= config.SOLAR_SURPLUS_THRESHOLD_W
        evening = period(now) == "peak"
        rate = config.TARIFF_NORMAL_INR_PER_KWH
        total_w = 0.0
        for t in tanks:
            w = float(t.get("pump_w") or 0) if t.get("pump_on") else 0.0
            total_w += w
            if w <= 0:
                continue
            wh = w * dt_s / 3600
            real_kwh = wh * REAL_SCALE / 1000
            b = self.per_building.setdefault(t["building_id"], {"wh": 0.0, "wh_green": 0.0, "cost_tod": 0.0, "cost_flat": 0.0})
            b["wh"] += wh
            b["wh_green"] += wh if green else 0.0
            b["cost_tod"] += real_kwh * rate * factor(now)
            b["cost_flat"] += real_kwh * rate
            self.totals["wh_pumped"] += wh
            self.totals["wh_green"] += wh if green else 0.0
            self.totals["wh_evening"] += wh if evening else 0.0
            self.totals["cost_tod_inr"] += real_kwh * rate * factor(now)
            self.totals["cost_flat_inr"] += real_kwh * rate
        if paused:
            self.totals["pause_seconds"] += dt_s
        self._sample(now, total_w, solar_w, feeder_load_w)

    def record_pause(self, now: datetime, shed_w: float):
        self._roll_day(to_ist(now).date())
        self.totals["pause_events"] += 1
        self.totals["max_shed_w"] = max(self.totals["max_shed_w"], shed_w)

    def _sample(self, now: datetime, pump_w: float, solar_w: float, load_w: float | None):
        bucket = now.replace(minute=now.minute - now.minute % SAMPLE_MIN, second=0, microsecond=0, tzinfo=None)
        if self._bucket is not None and bucket != self._bucket and self._acc["n"]:
            a = self._acc
            db = SessionLocal()
            try:
                db.merge(models.LoadSample(
                    ts=self._bucket, pump_w=a["pump_w"] / a["n"], solar_w=a["solar_w"] / a["n"],
                    feeder_load_w=a["load_w"] / a["load_n"] if a["load_n"] else None))
                db.commit()
            finally:
                db.close()
            self._acc = {"n": 0, "pump_w": 0.0, "solar_w": 0.0, "load_w": 0.0, "load_n": 0}
        self._bucket = bucket
        self._acc["n"] += 1
        self._acc["pump_w"] += pump_w
        self._acc["solar_w"] += solar_w
        if load_w is not None:
            self._acc["load_w"] += load_w
            self._acc["load_n"] += 1

    def persist(self):
        if self.day is None:
            return
        db = SessionLocal()
        try:
            db.merge(models.DailyImpact(day=self.day, **self.totals))
            db.commit()
        finally:
            db.close()

    def summary(self) -> dict:
        t = self.totals
        pumped = t["wh_pumped"]
        return {
            "day": self.day.isoformat() if self.day else None,
            "wh_pumped": round(pumped, 2),
            "green_share_pct": round(100 * t["wh_green"] / pumped, 1) if pumped else None,
            "wh_evening_peak": round(t["wh_evening"], 2),
            "tod_saving_inr": round(t["cost_flat_inr"] - t["cost_tod_inr"], 2),
            "pause_events": int(t["pause_events"]),
            "pause_minutes": round(t["pause_seconds"] / 60, 1),
            "max_shed_w": round(t["max_shed_w"], 1),
            "note": "Energy in model watts; rupees scaled to a real 0.75 HP pump at time-of-day rates.",
        }
