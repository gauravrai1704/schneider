from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


def now():
    return datetime.now(timezone.utc)


class Building(Base):
    __tablename__ = "buildings"

    id = Column(String, primary_key=True)          # e.g. "tank-01"
    name = Column(String, default="")
    feeder_id = Column(String, default="feeder-1")   # which grid feeder it belongs to
    tank_capacity_l = Column(Float, default=1000.0)

    telemetry = relationship("TankTelemetry", back_populates="building")


class TankTelemetry(Base):
    __tablename__ = "tank_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    building_id = Column(String, ForeignKey("buildings.id"))
    level_pct = Column(Float)
    pump_on = Column(Boolean)
    pump_w = Column(Float)
    ts = Column(DateTime, default=now)

    building = relationship("Building", back_populates="telemetry")


class SolarTelemetry(Base):
    __tablename__ = "solar_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    solar_w = Column(Float)
    lux = Column(Float)
    ts = Column(DateTime, default=now)


class PumpCommand(Base):
    __tablename__ = "pump_commands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    building_id = Column(String, ForeignKey("buildings.id"))
    action = Column(String)      # "ON" / "OFF"
    reason = Column(String)      # human-readable: why the scheduler decided this
    ts = Column(DateTime, default=now)


class ForecastRecord(Base):
    __tablename__ = "forecast_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    horizon_min = Column(Integer)     # minutes ahead this forecast is for
    solar_w = Column(Float)
    feeder_load_w = Column(Float)
    ts = Column(DateTime, default=now)
