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
