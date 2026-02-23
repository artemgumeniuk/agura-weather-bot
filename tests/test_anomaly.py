from datetime import date, timedelta

from app.models import ObsDaily
from app.services.anomaly import compute_precip_streak, percentile_rank, z_score


def test_percentile_rank_basic():
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile_rank(values, 3.0) == 75.0


def test_z_score_zero_std():
    assert z_score(10.0, 10.0, 0.0) == 0.0


def test_precip_streak_stops_at_zero():
    today = date(2026, 2, 20)
    rows = [
        ObsDaily(station_id=1, date=today, precip_sum=1.0),
        ObsDaily(station_id=1, date=today - timedelta(days=1), precip_sum=0.4),
        ObsDaily(station_id=1, date=today - timedelta(days=2), precip_sum=0.0),
        ObsDaily(station_id=1, date=today - timedelta(days=3), precip_sum=4.0),
    ]
    assert compute_precip_streak(rows, today) == 2
