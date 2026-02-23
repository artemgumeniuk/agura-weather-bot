import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    web_stateless_mode: bool = False
    database_url: str = "sqlite:///data/weatherbot.db"
    default_timezone: str = "Europe/Stockholm"
    daily_digest_hour: int = 7
    daily_digest_minute: int = 30

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_bot_url: str = ""
    app_logo_url: str = ""
    telegram_allowed_user_id: str | None = None

    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    smhi_metobs_base_url: str = "https://opendata-download-metobs.smhi.se"
    smhi_metfcst_base_url: str = "https://opendata-download-metfcst.smhi.se"
    weather_provider_default: str = "openmeteo"
    weather_provider_sweden: str = "smhi"
    openmeteo_base_url: str = "https://api.open-meteo.com"
    openmeteo_geo_base_url: str = "https://geocoding-api.open-meteo.com"
    history_warmup_years: int = 30
    history_warmup_batch_size: int = 20

    @property
    def telegram_allowed_user_id_int(self) -> int | None:
        if self.telegram_allowed_user_id in ("", None):
            return None
        try:
            return int(self.telegram_allowed_user_id)
        except (TypeError, ValueError):
            return None

    @property
    def stateless_runtime_enabled(self) -> bool:
        if self.web_stateless_mode:
            return True
        # Vercel serverless should default to stateless behavior unless explicitly overridden.
        return os.getenv("VERCEL") == "1"


settings = Settings()
