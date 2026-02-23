from app.services.comfort import ComfortModelService


def _row(i: int):
    snapshot = {
        "t": float(i),
        "comfort_temp": float(i),
        "ws": 3.0,
        "gust": 4.0,
        "r": 60.0,
        "tp": 0.1,
        "pmean": 0.1,
    }
    return snapshot, "walking", 30, (i % 5) + 1


def test_model_threshold_requires_10_samples():
    svc = ComfortModelService()
    rows = [_row(i) for i in range(9)]
    assert svc.fit(rows) is False


def test_model_predict_after_training():
    svc = ComfortModelService()
    rows = [_row(i) for i in range(12)]
    assert svc.fit(rows) is True
    pred = svc.predict(rows[-1][0], "walking", 30)
    assert 1.0 <= pred.predicted_rating <= 5.0
    assert pred.model_ready is True
