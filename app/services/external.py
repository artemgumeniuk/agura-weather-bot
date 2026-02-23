from __future__ import annotations

import csv
import io
import math
from datetime import UTC, datetime

import httpx

from app.config import settings


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class GeocoderClient:
    async def geocode_city(self, city: str) -> tuple[float, float, str]:
        url = f"{settings.nominatim_base_url}/search"
        params = {"q": city, "format": "jsonv2", "limit": 1}
        headers = {"User-Agent": "weather-dashboard-bot/0.1"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        if not payload:
            raise ValueError(f"No geocoding result for city: {city}")
        first = payload[0]
        return float(first["lat"]), float(first["lon"]), first.get("display_name", city)


class SmhiObsClient:
    base_url = settings.smhi_metobs_base_url

    async def fetch_parameter(self, parameter_id: int) -> dict:
        url = f"{self.base_url}/api/version/1.0/parameter/{parameter_id}.json"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def nearest_station(self, lat: float, lon: float, parameter_id: int = 4) -> int:
        feed = await self.fetch_parameter(parameter_id)
        stations = feed.get("station", [])
        if not stations:
            raise ValueError("No stations in SMHI parameter feed")

        best_station: int | None = None
        best_dist = float("inf")
        for station in stations:
            if station.get("active") is False:
                continue
            slat = station.get("latitude") or station.get("lat")
            slon = station.get("longitude") or station.get("lon")
            if slat is None or slon is None:
                continue
            dist = haversine_km(lat, lon, float(slat), float(slon))
            if dist < best_dist:
                best_dist = dist
                best_station = int(station["id"])
        if best_station is None:
            raise ValueError("No station with coordinates found")
        return best_station

    async def fetch_station_period_json(self, parameter_id: int, station_id: int, period: str) -> dict:
        url = (
            f"{self.base_url}/api/version/1.0/parameter/{parameter_id}/station/{station_id}/"
            f"period/{period}/data.json"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def fetch_corrected_archive_csv(self, parameter_id: int, station_id: int) -> list[dict]:
        url = (
            f"{self.base_url}/api/version/1.0/parameter/{parameter_id}/station/{station_id}/"
            "period/corrected-archive/data.csv"
        )
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text

        # SMHI CSV has metadata lines and at least two observed row layouts:
        # 1) "<iso-datetime>;<value>;..."
        # 2) "<date>;<time>;<value>;..."
        rows: list[dict] = []
        reader = csv.reader(io.StringIO(text), delimiter=";")
        for line in reader:
            if not line:
                continue
            # Layout 1: ISO datetime in first column.
            c0 = line[0].strip() if len(line) > 0 else ""
            if "T" in c0 and "-" in c0:
                try:
                    dt = datetime.fromisoformat(c0.replace("Z", "+00:00")).astimezone(UTC)
                    val = float((line[1] if len(line) > 1 else "").replace(",", "."))
                    rows.append({"datetime": dt, "value": val})
                    continue
                except Exception:
                    pass

            # Layout 2: Date + time split in first two columns.
            c1 = line[1].strip() if len(line) > 1 else ""
            c2 = line[2].strip() if len(line) > 2 else ""
            if "-" in c0 and ":" in c1 and c2:
                try:
                    dt = datetime.fromisoformat(f"{c0} {c1}").replace(tzinfo=UTC)
                    val = float(c2.replace(",", "."))
                    rows.append({"datetime": dt, "value": val})
                    continue
                except Exception:
                    pass
        return rows


class SmhiForecastClient:
    base_url = settings.smhi_metfcst_base_url

    async def fetch_point_forecast(self, lon: float, lat: float) -> dict:
        # SMHI point endpoint can be sensitive to coordinate formatting.
        # Try high precision first, then normalized rounded fallback.
        candidates = [
            (lon, lat),
            (round(lon, 6), round(lat, 6)),
            (round(lon, 4), round(lat, 4)),
            (round(lon, 2), round(lat, 2)),
        ]
        headers = {"User-Agent": "weather-dashboard-bot/0.1"}
        async with httpx.AsyncClient(timeout=30) as client:
            last_exc: Exception | None = None
            for xlon, xlat in candidates:
                url = (
                    f"{self.base_url}/api/category/pmp3g/version/2/geotype/point/"
                    f"lon/{xlon}/lat/{xlat}/data.json"
                )
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    if exc.response.status_code == 404:
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Failed to fetch SMHI forecast")


def parse_pmp3g_timeseries(payload: dict) -> list[dict]:
    out: list[dict] = []
    for item in payload.get("timeSeries", []):
        params = {p["name"]: p["values"][0] for p in item.get("parameters", []) if p.get("values")}
        out.append(
            {
                "valid_time": datetime.fromisoformat(item["validTime"].replace("Z", "+00:00")).astimezone(UTC),
                "t": float(params.get("t", 0.0)),
                "ws": float(params.get("ws", 0.0)),
                "gust": float(params.get("gust", params.get("ws", 0.0))),
                "r": float(params.get("r", 0.0)),
                "tp": float(params.get("tp", 0.0)),
                "pmean": float(params.get("pmean", 0.0)),
            }
        )
    return out
