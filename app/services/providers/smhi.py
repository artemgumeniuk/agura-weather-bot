from __future__ import annotations

from datetime import UTC, date

from app.services.external import GeocoderClient, SmhiForecastClient, SmhiObsClient, parse_pmp3g_timeseries
from app.services.providers.base import DailyHistoryPoint, ForecastPoint, GeocodeResult


def _group_daily(rows: list[dict]) -> dict[date, list[float]]:
    out: dict[date, list[float]] = {}
    for row in rows:
        day = row["datetime"].date()
        out.setdefault(day, []).append(float(row["value"]))
    return out


class SmhiProvider:
    provider_name = "smhi"

    def __init__(self) -> None:
        self.geocoder = GeocoderClient()
        self.obs = SmhiObsClient()
        self.fc = SmhiForecastClient()

    async def geocode_city(self, city: str) -> GeocodeResult:
        lat, lon, display_name = await self.geocoder.geocode_city(city)
        station_id = await self.obs.nearest_station(lat, lon)
        location_key = f"{self.provider_name}:station:{station_id}"
        return GeocodeResult(
            lat=lat,
            lon=lon,
            display_name=display_name,
            country_code="SE",
            timezone="Europe/Stockholm",
            provider_location_key=location_key,
            provider=self.provider_name,
            station_id=station_id,
        )

    async def fetch_forecast(self, lat: float, lon: float) -> list[ForecastPoint]:
        payload = await self.fc.fetch_point_forecast(lon=lon, lat=lat)
        rows = parse_pmp3g_timeseries(payload)
        return [
            ForecastPoint(
                valid_time=r["valid_time"].astimezone(UTC),
                t=r["t"],
                ws=r["ws"],
                gust=r["gust"],
                r=r["r"],
                tp=r["tp"],
                pmean=r["pmean"],
            )
            for r in rows
        ]

    async def fetch_daily_history(
        self,
        lat: float,
        lon: float,
        start_date: date,
        end_date: date,
    ) -> list[DailyHistoryPoint]:
        station_id = await self.obs.nearest_station(lat, lon)
        temp_rows = await self.obs.fetch_corrected_archive_csv(1, station_id)
        wind_rows = await self.obs.fetch_corrected_archive_csv(4, station_id)
        precip_rows = await self.obs.fetch_corrected_archive_csv(5, station_id)
        rh_rows = await self.obs.fetch_corrected_archive_csv(6, station_id)

        t = _group_daily(temp_rows)
        w = _group_daily(wind_rows)
        p = _group_daily(precip_rows)
        h = _group_daily(rh_rows)

        days = set(t.keys()) | set(w.keys()) | set(p.keys()) | set(h.keys())
        out: list[DailyHistoryPoint] = []
        for day in sorted(days):
            if day < start_date or day > end_date:
                continue
            out.append(
                DailyHistoryPoint(
                    date=day,
                    t_mean=(sum(t[day]) / len(t[day])) if day in t and t[day] else None,
                    ws_mean=(sum(w[day]) / len(w[day])) if day in w and w[day] else None,
                    precip_sum=sum(p[day]) if day in p and p[day] else 0.0,
                    rh_mean=(sum(h[day]) / len(h[day])) if day in h and h[day] else None,
                )
            )
        return out
