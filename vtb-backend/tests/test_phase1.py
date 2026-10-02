import asyncio
from datetime import datetime

from app.bus import Bus, topic_matches
from app.clock import to_ist
from app.config import IST, PERSONS_PER_BUILDING, WATER_LPCD
from app.scheduler import Scheduler, TankSnapshot
from app.water import daily_litres, draw_litres_per_hr, water_use_forecast


def test_topic_matching():
    assert topic_matches("vtb/tank/+/telemetry", "vtb/tank/tank-01/telemetry")
    assert not topic_matches("vtb/tank/+/telemetry", "vtb/tank/tank-01/cmd")
    assert not topic_matches("vtb/tank/+/telemetry", "vtb/tank/a/b/telemetry")
    assert topic_matches("vtb/#", "vtb/solar/telemetry")
    assert topic_matches("vtb/solar/telemetry", "vtb/solar/telemetry")


def test_bus_wildcard_dispatch():
    bus, got = Bus(), []

    async def handler(topic, payload):
        got.append((topic, payload["x"]))

    bus.subscribe("vtb/tank/+/telemetry", handler)
    asyncio.run(bus.publish("vtb/tank/tank-07/telemetry", {"x": 1}))
    asyncio.run(bus.publish("vtb/solar/telemetry", {"x": 2}))
    assert got == [("vtb/tank/tank-07/telemetry", 1)]


def test_naive_datetimes_are_ist():
    assert to_ist(datetime(2026, 1, 1, 12)).utcoffset() == IST.utcoffset(None)


def test_water_daily_total_matches_cpheeo_norm():
    day = datetime(2026, 3, 1, tzinfo=IST)
    total = sum(draw_litres_per_hr(day.replace(hour=m // 60, minute=m % 60), "tank-01") / 60
                for m in range(24 * 60))
    assert abs(total - daily_litres("tank-01")) / daily_litres("tank-01") < 0.01
    base = WATER_LPCD * PERSONS_PER_BUILDING
    assert 0.8 * base <= daily_litres("tank-01") <= 1.2 * base


def test_water_is_deterministic_and_peaks_in_morning():
    t = datetime(2026, 3, 1, 7, 30, tzinfo=IST)
    assert water_use_forecast(t, "tank-03") == water_use_forecast(t, "tank-03")
    assert draw_litres_per_hr(t, "tank-03") > 5 * draw_litres_per_hr(t.replace(hour=3), "tank-03")


def test_dry_run_uses_sump_not_tank():
    s = Scheduler()
    noon = datetime(2026, 3, 1, 12, tzinfo=IST)
    dry = s.decide([TankSnapshot("a", 40.0, sump_level_pct=5.0)], 500.0, noon)[0]
    assert dry.action == "OFF" and "dry-run" in dry.reason
    empty_tank = Scheduler().decide([TankSnapshot("b", 0.0, sump_level_pct=80.0)], 500.0, noon)[0]
    assert empty_tank.action == "ON"
