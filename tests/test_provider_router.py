from app.config import settings
from app.services.providers.router import ProviderRouter


def test_router_uses_smhi_for_sweden_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "weather_provider_sweden", "smhi")
    router = ProviderRouter()
    provider = router.provider_for_country("SE")
    assert provider.provider_name == "smhi"


def test_router_uses_openmeteo_for_non_sweden(monkeypatch):
    monkeypatch.setattr(settings, "weather_provider_sweden", "smhi")
    router = ProviderRouter()
    provider = router.provider_for_country("US")
    assert provider.provider_name == "openmeteo"


def test_router_uses_openmeteo_for_sweden_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "weather_provider_sweden", "openmeteo")
    router = ProviderRouter()
    provider = router.provider_for_country("SE")
    assert provider.provider_name == "openmeteo"
