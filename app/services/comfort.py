from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

FEATURES = ["t", "comfort_temp", "ws", "gust", "r", "tp", "pmean", "activity_code", "minutes_outside"]


def activity_to_code(activity: str) -> float:
    return {"standing": 0.0, "walking": 1.0, "running": 2.0}.get(activity, 1.0)


def vectorize(snapshot: dict, activity: str, minutes_outside: int) -> list[float]:
    return [
        float(snapshot.get("t", 0.0)),
        float(snapshot.get("comfort_temp", snapshot.get("t", 0.0))),
        float(snapshot.get("ws", 0.0)),
        float(snapshot.get("gust", 0.0)),
        float(snapshot.get("r", 0.0)),
        float(snapshot.get("tp", 0.0)),
        float(snapshot.get("pmean", 0.0) or 0.0),
        activity_to_code(activity),
        float(minutes_outside),
    ]


@dataclass
class ComfortPrediction:
    predicted_rating: float
    bad_day_probability: float
    tailored_adjustments: list[str]
    model_ready: bool


class ComfortModelService:
    def __init__(self) -> None:
        self._model = GradientBoostingRegressor(random_state=42)
        self._trained = False

    @property
    def min_samples(self) -> int:
        return 10

    def fit(self, rows: list[tuple[dict, str, int, int]]) -> bool:
        if len(rows) < self.min_samples:
            self._trained = False
            return False
        x = np.array([vectorize(snapshot, activity, mins) for snapshot, activity, mins, _ in rows])
        y = np.array([rating for _, _, _, rating in rows], dtype=float)
        self._model.fit(x, y)
        self._trained = True
        return True

    def predict(self, snapshot: dict, activity: str, minutes_outside: int) -> ComfortPrediction:
        if not self._trained:
            base = float(snapshot.get("comfort_temp", snapshot.get("t", 0.0)))
            cold_penalty = 1.0 if base < 0 else 0.0
            wet_penalty = 1.0 if snapshot.get("tp", 0.0) > 0.6 else 0.0
            wind_penalty = 0.8 if snapshot.get("ws", 0.0) > 9 else 0.0
            predicted = max(1.0, min(5.0, 4.8 - cold_penalty - wet_penalty - wind_penalty))
            bad_prob = max(0.0, min(1.0, (2.5 - predicted) / 2.0 + 0.4))
            return ComfortPrediction(
                predicted_rating=predicted,
                bad_day_probability=bad_prob,
                tailored_adjustments=_tailored_adjustments(snapshot, predicted),
                model_ready=False,
            )

        vec = np.array([vectorize(snapshot, activity, minutes_outside)])
        pred = float(self._model.predict(vec)[0])
        pred = max(1.0, min(5.0, pred))
        bad_prob = max(0.0, min(1.0, (2.2 - pred) / 1.8 + 0.35))
        return ComfortPrediction(
            predicted_rating=pred,
            bad_day_probability=bad_prob,
            tailored_adjustments=_tailored_adjustments(snapshot, pred),
            model_ready=True,
        )


def _tailored_adjustments(snapshot: dict, predicted_rating: float) -> list[str]:
    items: list[str] = []
    if predicted_rating <= 2.2:
        items.append("upgrade to warmer mid-layer")
    if snapshot.get("tp", 0.0) > 0.6:
        items.append("use waterproof shell and shoes")
    if snapshot.get("ws", 0.0) > 10:
        items.append("prioritize windproof outer layer")
    if not items:
        items.append("current outfit plan should be comfortable")
    return items
