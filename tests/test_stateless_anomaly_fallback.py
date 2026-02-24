from datetime import date
from types import SimpleNamespace

from app.models import ObsDaily
from app.services.app_logic import AppLogic


def test_stateless_anomaly_marks_history_temporarily_unavailable():
    logic = AppLogic()
    user_like = SimpleNamespace(
        station_id=123,
        location_key="openmeteo:1.0000,2.0000",
        weather_provider="openmeteo",
    )
    today_row = ObsDaily(
        station_id=123,
        location_key="openmeteo:1.0000,2.0000",
        provider="openmeteo",
        date=date(2026, 2, 24),
        t_mean=2.0,
        ws_mean=1.0,
        precip_sum=0.0,
        rh_mean=70.0,
    )

    anomaly = logic._anomaly_from_stateless_data(
        user_like,
        today_row=today_row,
        history_rows=[],
        history_temporarily_unavailable=True,
    )

    assert anomaly.confidence_note == "history baseline temporarily unavailable"
    assert anomaly.weirdness_score == 0.0
