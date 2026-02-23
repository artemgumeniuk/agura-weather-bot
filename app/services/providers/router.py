from __future__ import annotations

from app.config import settings
from app.services.providers.base import WeatherProvider
from app.services.providers.openmeteo import OpenMeteoProvider
from app.services.providers.smhi import SmhiProvider


class ProviderRouter:
    def __init__(self) -> None:
        self.openmeteo = OpenMeteoProvider()
        self.smhi = SmhiProvider()

    async def geocode_city(self, city: str):
        # Open-Meteo geocoding is global and returns timezone + country.
        return await self.openmeteo.geocode_city(city)

    def provider_for_country(self, country_code: str | None) -> WeatherProvider:
        cc = (country_code or "").upper()
        if cc == "SE" and settings.weather_provider_sweden.lower() == "smhi":
            return self.smhi
        return self.openmeteo

    def provider_for_name(self, name: str) -> WeatherProvider:
        if (name or "").lower() == "smhi":
            return self.smhi
        return self.openmeteo
