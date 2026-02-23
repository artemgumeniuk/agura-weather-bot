from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class TodayVsHistoryResponse(BaseModel):
    date: date
    station_id: int | None = None
    location_key: str = ""
    provider: str = "smhi"
    temp_anomaly_c: float
    temp_percentile: float
    precip_streak_days: int
    z_temp: float
    z_wind: float
    z_precip: float
    weirdness_score: float
    baseline_years: int
    confidence_note: str


class OutfitResponse(BaseModel):
    base_layer: str
    mid_layer: str
    shell: str
    shoes: str
    extras: list[str]
    rationale: list[str]


class ComfortRatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    context: dict[str, Any] | None = None
    activity: str = "walking"
    minutes_outside: int = Field(default=30, ge=10, le=180)


class ComfortPredictResponse(BaseModel):
    predicted_rating: float
    bad_day_probability: float
    tailored_adjustments: list[str]
    model_ready: bool


class DashboardViewModel(BaseModel):
    anomaly: TodayVsHistoryResponse
    outfit: OutfitResponse
