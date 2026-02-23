from datetime import date, timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.models import ObsDaily
from app.services.app_logic import AppLogic


class FakeGeocoder:
    async def geocode_city(self, city: str):
        return 59.3293, 18.0686, "Stockholm"


class FakeObsClient:
    async def nearest_station(self, lat: float, lon: float, parameter_id: int = 4) -> int:
        return 12345


class FakeWeather:
    async def ingest_forecast(self, session, lat, lon):
        return []

    async def ingest_latest_obs(self, session, station_id):
        today = date.today()
        session.add(
            ObsDaily(
                station_id=station_id,
                date=today,
                t_mean=2.0,
                ws_mean=5.0,
                precip_sum=1.0,
            )
        )
        for i in range(1, 200):
            session.add(
                ObsDaily(
                    station_id=station_id,
                    date=today - timedelta(days=i),
                    t_mean=float((i % 20) - 5),
                    ws_mean=3.0 + (i % 3),
                    precip_sum=float(i % 2),
                )
            )
        session.commit()

    async def import_corrected_archive(self, session, station_id):
        return None

    def compute_today_vs_history(self, session, station_id):
        return {
            "date": date.today(),
            "station_id": station_id,
            "temp_anomaly_c": 1.2,
            "temp_percentile": 88.0,
            "precip_streak_days": 2,
            "z_temp": 1.0,
            "z_wind": 0.3,
            "z_precip": 0.6,
            "weirdness_score": 1.2,
            "baseline_years": 5,
            "confidence_note": "medium confidence baseline using ~5 years",
        }


def test_set_city_and_today_vs_history():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    logic = AppLogic()
    logic.geocoder = FakeGeocoder()
    logic.obs_client = FakeObsClient()
    logic.weather = FakeWeather()

    import asyncio

    with Session(engine) as session:
        user = asyncio.run(logic.set_city(session, telegram_id=1, city="Stockholm"))
        assert user.station_id == 12345

        anomaly = logic.today_vs_history(session, user)
        assert anomaly.station_id == 12345
        assert anomaly.weirdness_score > 0
