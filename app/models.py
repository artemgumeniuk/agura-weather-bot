from __future__ import annotations

from datetime import date as date_t
from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.sqlite import JSON
from sqlmodel import Field, SQLModel


class UserProfile(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    telegram_id: int = Field(index=True, unique=True)
    city: str
    lat: float
    lon: float
    timezone: str = "Europe/Stockholm"
    station_id: int | None = Field(default=None, index=True)
    weather_provider: str = "smhi"
    location_key: str = Field(default="", index=True)
    country_code: str | None = None
    history_ready: bool = False
    history_last_refreshed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ObsDaily(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    station_id: int | None = Field(default=None, index=True)
    location_key: str = Field(default="", index=True)
    provider: str = "smhi"
    date: date_t = Field(index=True)
    t_mean: float | None = None
    t_min: float | None = None
    t_max: float | None = None
    ws_mean: float | None = None
    precip_sum: float | None = None
    rh_mean: float | None = None


class ForecastHourly(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    location_key: str = Field(default="", index=True)
    provider: str = "smhi"
    lat: float = Field(index=True)
    lon: float = Field(index=True)
    valid_time: datetime = Field(index=True)
    t: float
    ws: float
    gust: float
    r: float
    tp: float
    pmean: float | None = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class ComfortRating(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    telegram_id: int = Field(index=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    rating: int
    activity: str = "walking"
    minutes_outside: int = 30
    weather_feature_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False, default=dict)
    )


class ComfortModelMeta(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    telegram_id: int = Field(index=True, unique=True)
    model_version: str = "gbr_v1"
    trained_at: datetime | None = None
    sample_count: int = 0
    metrics: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False, default=dict))


class DailyDigestLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    telegram_id: int = Field(index=True)
    date: date_t = Field(index=True)
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    payload_hash: str
