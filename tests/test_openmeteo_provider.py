import asyncio
from datetime import date

import httpx

from app.services.providers.openmeteo import OpenMeteoProvider


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *args, **kwargs):
        return _FakeResponse(self.payload)


def test_openmeteo_geocode_mapping(monkeypatch):
    payload = {
        "results": [
            {
                "name": "Boston",
                "latitude": 42.3601,
                "longitude": -71.0589,
                "country": "United States",
                "country_code": "US",
                "admin1": "Massachusetts",
                "timezone": "America/New_York",
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=20: _FakeAsyncClient(payload))
    provider = OpenMeteoProvider()
    result = asyncio.run(provider.geocode_city("Boston"))
    assert result.provider == "openmeteo"
    assert result.country_code == "US"
    assert result.timezone == "America/New_York"
    assert result.provider_location_key.startswith("openmeteo:")


def test_openmeteo_history_mapping(monkeypatch):
    payload = {
        "daily": {
            "time": ["2026-02-20", "2026-02-21"],
            "temperature_2m_mean": [1.0, 2.0],
            "wind_speed_10m_mean": [10.8, 7.2],
            "precipitation_sum": [0.0, 1.2],
            "relative_humidity_2m_mean": [70.0, 80.0],
        }
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=60: _FakeAsyncClient(payload))
    provider = OpenMeteoProvider()
    rows = asyncio.run(provider.fetch_daily_history(57.7, 11.9, date(2026, 2, 20), date(2026, 2, 21)))
    assert len(rows) == 2
    assert rows[0].date.isoformat() == "2026-02-20"
    assert rows[0].ws_mean == 3.0  # km/h -> m/s conversion
    assert rows[1].precip_sum == 1.2


def test_openmeteo_history_mapping_with_missing_optional_humidity(monkeypatch):
    payload = {
        "daily": {
            "time": ["2026-02-20", "2026-02-21"],
            "temperature_2m_mean": [1.0, 2.0],
            "wind_speed_10m_mean": [10.8, 7.2],
            "precipitation_sum": [0.0, 1.2],
            # relative_humidity_2m_mean intentionally missing
        }
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=60: _FakeAsyncClient(payload))
    provider = OpenMeteoProvider()
    rows = asyncio.run(provider.fetch_daily_history(57.7, 11.9, date(2026, 2, 20), date(2026, 2, 21)))
    assert len(rows) == 2
    assert rows[0].rh_mean is None
    assert rows[1].ws_mean == 2.0
