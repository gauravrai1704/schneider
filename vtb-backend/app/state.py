"""
Live in-memory state shared by the control loop and the API routes.
The database keeps history; this keeps what the loop needs right now.
"""
from __future__ import annotations
from collections import deque
from datetime import datetime

from app.alerts import LeakDetector
from app.impact import ImpactTracker
from app.scheduler import Decision, Scheduler

scheduler = Scheduler()
latest_tanks: dict[str, dict] = {}                 # building_id -> latest telemetry
last_decisions: dict[str, Decision] = {}           # building_id -> latest scheduler decision
last_sent: dict[str, tuple[str, float]] = {}       # building_id -> (action, monotonic time) last published
clearness_history: deque[tuple[datetime, float]] = deque(maxlen=2000)   # ~70 min of panel readings
live = {"solar_w": 0.0, "clearness": None, "feeder_load_w": None, "mock_running": False}
leaks = LeakDetector()
impact = ImpactTracker()
