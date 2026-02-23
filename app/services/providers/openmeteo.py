from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from app.config import settings
from app.services.providers.base import DailyHistoryPoint, ForecastPoint, GeocodeResult


class OpenMeteoProvider:
    provider_name = "openmeteo"

    async def geocode_city(self, city: str) -> GeocodeResult:
        url = f"{settings.openmeteo_geo_base_url}/v1/search"
        params = {"name": city, "count": 1, "language": "en", "format": "json"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        results = payload.get("results") or []
        if not results:
            raise ValueError(f"No geocoding result for city: {city}")
        first = results[0]
        lat = float(first["latitude"])
        lon = float(first["longitude"])
        country_code = (first.get("country_code") or "").upper() or None
        timezone = first.get("timezone")
        name = first.get("name") or city
        country = first.get("country") or ""
        admin1 = first.get("admin1") or ""
        pieces = [name, admin1, country]
        display_name = ", ".join([p for p in pieces if p])
        location_key = f"{self.provider_name}:{lat:.4f},{lon:.4f}"
        return GeocodeResult(
            lat=lat,
            lon=lon,
            display_name=display_name,
            country_code=country_code,
            timezone=timezone,
            provider_location_key=location_key,
            provider=self.provider_name,
        )

    async def fetch_forecast(self, lat: float, lon: float) -> list[ForecastPoint]:
        url = f"{settings.openmeteo_base_url}/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "precipitation",
                    "wind_speed_10m",
                    "wind_gusts_10m",
                ]
            ),
            "forecast_days": 7,
            "timezone": "UTC",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        humidity = hourly.get("relative_humidity_2m") or []
        precip = hourly.get("precipitation") or []
        ws = hourly.get("wind_speed_10m") or []
        gust = hourly.get("wind_gusts_10m") or []

        n = min(len(times), len(temps), len(humidity), len(precip), len(ws), len(gust))
        out: list[ForecastPoint] = []
        for i in range(n):
            valid_time = datetime.fromisoformat(str(times[i])).replace(tzinfo=UTC)
            out.append(
                ForecastPoint(
                    valid_time=valid_time,
                    t=float(temps[i]),
                    ws=float(ws[i]) / 3.6,  # km/h -> m/s
                    gust=float(gust[i]) / 3.6,  # km/h -> m/s
                    r=float(humidity[i]),
                    tp=float(precip[i]),
                    pmean=float(precip[i]),
                )
            )
        return out

    async def fetch_daily_history(
        self,
        lat: float,
        lon: float,
        start_date: date,
        end_date: date,
    ) -> list[DailyHistoryPoint]:
        url = f"{settings.openmeteo_base_url}/v1/archive"
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join(
                [
                    "temperature_2m_mean",
                    "wind_speed_10m_mean",
                    "precipitation_sum",
                    "relative_humidity_2m_mean",
                ]
            ),
            "timezone": "UTC",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        t_mean = daily.get("temperature_2m_mean") or []
        ws_mean = daily.get("wind_speed_10m_mean") or []
        precip_sum = daily.get("precipitation_sum") or []
        rh_mean = daily.get("relative_humidity_2m_mean") or []

        # Some Open-Meteo archive responses may omit optional series (for example humidity).
        # Do not collapse to zero rows when an optional series is missing.
        n = len(times)
        out: list[DailyHistoryPoint] = []
        for i in range(n):
            t_val = float(t_mean[i]) if i < len(t_mean) and t_mean[i] is not None else None
            ws_val = (float(ws_mean[i]) / 3.6) if i < len(ws_mean) and ws_mean[i] is not None else None
            p_val = float(precip_sum[i]) if i < len(precip_sum) and precip_sum[i] is not None else None
            rh_val = float(rh_mean[i]) if i < len(rh_mean) and rh_mean[i] is not None else None
            out.append(
                DailyHistoryPoint(
                    date=date.fromisoformat(str(times[i])),
                    t_mean=t_val,
                    ws_mean=ws_val,  # km/h -> m/s
                    precip_sum=p_val,
                    rh_mean=rh_val,
                )
            )
        return out
