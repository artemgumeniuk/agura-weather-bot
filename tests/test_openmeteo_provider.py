from datetime import date

import respx
from httpx import Response

from app.config import settings
from app.services.providers.openmeteo import OpenMeteoProvider


@respx.mock
async def test_fetch_daily_history_uses_archive_base_url(monkeypatch):
    monkeypatch.setattr(settings, "openmeteo_archive_base_url", "https://archive-api.open-meteo.com")
    route = respx.get("https://archive-api.open-meteo.com/v1/archive").mock(
        return_value=Response(
            200,
            json={
                "daily": {
                    "time": ["2026-02-20"],
                    "temperature_2m_mean": [5.0],
                    "wind_speed_10m_mean": [18.0],  # km/h
                    "precipitation_sum": [1.2],
                    "relative_humidity_2m_mean": [80.0],
                }
            },
        )
    )

    provider = OpenMeteoProvider()
    rows = await provider.fetch_daily_history(
        lat=57.7071,
        lon=11.9668,
        start_date=date(2026, 2, 20),
        end_date=date(2026, 2, 20),
    )

    assert route.called
    assert len(rows) == 1
    assert rows[0].date.isoformat() == "2026-02-20"
    assert rows[0].ws_mean == 5.0  # converted to m/s


@respx.mock
async def test_geocode_city_retries_with_base_name_when_display_name_fails():
    route_full = respx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": "Gothenburg, Västra Götaland, Sweden",
            "count": "1",
            "language": "en",
            "format": "json",
        },
    ).mock(return_value=Response(200, json={"results": []}))
    route_base = respx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": "Gothenburg",
            "count": "1",
            "language": "en",
            "format": "json",
        },
    ).mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "name": "Gothenburg",
                        "latitude": 57.7072,
                        "longitude": 11.9670,
                        "country_code": "SE",
                        "country": "Sweden",
                        "admin1": "Vastra Gotaland",
                        "timezone": "Europe/Stockholm",
                    }
                ]
            },
        )
    )

    provider = OpenMeteoProvider()
    result = await provider.geocode_city("Gothenburg, Västra Götaland, Sweden")

    assert route_full.called
    assert route_base.called
    assert result.lat == 57.7072
    assert result.lon == 11.967
