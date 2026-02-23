from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

import app.web as web_module
from app.db import get_session
from app.models import UserProfile
from app.schemas import OutfitResponse


class FakeLogic:
    async def set_city(self, session: Session, telegram_id: int, city: str) -> UserProfile:
        user = session.exec(select(UserProfile).where(UserProfile.telegram_id == telegram_id)).first()
        if user is None:
            user = UserProfile(
                telegram_id=telegram_id,
                city=f"{city}, Sweden",
                lat=57.7,
                lon=11.9,
                station_id=71420,
            )
        else:
            user.city = f"{city}, Sweden"
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    async def refresh_user_data(self, session: Session, user: UserProfile) -> None:
        return None

    def build_now_summary(self, session: Session, user: UserProfile) -> str:
        return (
            "Göteborg — just now\n"
            "🌡️ 1.5°C (comfort -1.0°C)\n"
            "💨 2.2 m/s · 💧 99% · ☔ 0.0 mm\n"
            "📊 Vs normal: -1.2°C · Weirdness: 1.4 (notable)\n"
            "Compared with typical weather for this date in your area, conditions are noticeable but not extreme.\n"
            "🕰️ Last year today: 4.1°C"
        )

    def build_stats_summary(self, session: Session, user: UserProfile) -> str:
        return "📈 Stats for Göteborg\n- Temp percentile: 35% (near normal)"

    def build_forecast_digest(self, session: Session, user: UserProfile, days: int) -> str:
        return f"📅 Forecast for {days} day(s)"

    def outfit_now(self, session: Session, user: UserProfile, minutes_outside: int, activity: str) -> OutfitResponse:
        return OutfitResponse(
            base_layer="thermal base layer",
            mid_layer="insulating fleece or wool",
            shell="insulated waterproof shell",
            shoes="waterproof shoes",
            extras=["gloves"],
            rationale=[],
        )


def _make_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(web_module.router)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(web_module, "logic", FakeLogic())
    return TestClient(app), engine


def test_root_without_user_shows_city_form(monkeypatch):
    client, _ = _make_client(monkeypatch)
    monkeypatch.setattr(web_module.settings, "telegram_bot_username", "")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Set City" in resp.text
    assert "Set TELEGRAM_BOT_URL to enable" in resp.text


def test_root_with_telegram_username_shows_bot_link(monkeypatch):
    client, _ = _make_client(monkeypatch)
    monkeypatch.setattr(web_module.settings, "telegram_bot_username", "my_weather_bot")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Open bot in Telegram" in resp.text
    assert "https://t.me/my_weather_bot" in resp.text


def test_set_city_returns_now_panel_with_buttons(monkeypatch):
    client, _ = _make_client(monkeypatch)
    resp = client.post("/web/set-city", data={"city": "Gothenburg"})
    assert resp.status_code == 200
    assert "Göteborg — just now" in resp.text
    assert "🧥 Outfit" in resp.text
    assert "📅 Forecast" in resp.text
    assert "📈 Stats" in resp.text
    assert "⚙️ Location" in resp.text


def test_stats_requires_city_first(monkeypatch):
    client, _ = _make_client(monkeypatch)
    resp = client.get("/web/stats")
    assert resp.status_code == 400
    assert "Set city first." in resp.text


def test_stats_with_city(monkeypatch):
    client, engine = _make_client(monkeypatch)
    with Session(engine) as session:
        session.add(UserProfile(telegram_id=1, city="Göteborg, Sweden", lat=57.7, lon=11.9, station_id=71420))
        session.commit()
    resp = client.get("/web/stats")
    assert resp.status_code == 200
    assert "📈 Stats for Göteborg" in resp.text


def test_forecast_invalid_days(monkeypatch):
    client, engine = _make_client(monkeypatch)
    with Session(engine) as session:
        session.add(UserProfile(telegram_id=1, city="Göteborg, Sweden", lat=57.7, lon=11.9, station_id=71420))
        session.commit()
    resp = client.get("/web/forecast?days=2")
    assert resp.status_code == 400
    assert "days must be 1 or 3" in resp.text


def test_outfit_invalid_params(monkeypatch):
    client, engine = _make_client(monkeypatch)
    with Session(engine) as session:
        session.add(UserProfile(telegram_id=1, city="Göteborg, Sweden", lat=57.7, lon=11.9, station_id=71420))
        session.commit()
    resp = client.get("/web/outfit?minutes=30&activity=walking")
    assert resp.status_code == 400
    assert "minutes must be one of 15, 60" in resp.text


def test_location_endpoint_returns_city_form(monkeypatch):
    client, _ = _make_client(monkeypatch)
    resp = client.post("/web/location")
    assert resp.status_code == 200
    assert "Set City" in resp.text
    assert "Send a new city name to update location." in resp.text
