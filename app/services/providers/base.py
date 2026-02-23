from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass
class GeocodeResult:
    lat: float
    lon: float
    display_name: str
    country_code: str | None
    timezone: str | None
    provider_location_key: str
    provider: str
    station_id: int | None = None


@dataclass
class ForecastPoint:
    valid_time: datetime
    t: float
    ws: float
    gust: float
    r: float
    tp: float
    pmean: float | None


@dataclass
class DailyHistoryPoint:
    date: date
    t_mean: float | None
    ws_mean: float | None
    precip_sum: float | None
    rh_mean: float | None


class WeatherProvider(Protocol):
    provider_name: str

    async def geocode_city(self, city: str) -> GeocodeResult:
        ...

    async def fetch_forecast(self, lat: float, lon: float) -> list[ForecastPoint]:
        ...

    async def fetch_daily_history(
        self,
        lat: float,
        lon: float,
        start_date: date,
        end_date: date,
    ) -> list[DailyHistoryPoint]:
        ...
