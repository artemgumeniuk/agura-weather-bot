from __future__ import annotations

import math
from datetime import date

from app.models import ObsDaily


def percentile_rank(sorted_values: list[float], value: float) -> float:
    if not sorted_values:
        return 50.0
    below_or_equal = sum(1 for v in sorted_values if v <= value)
    return (below_or_equal / len(sorted_values)) * 100.0


def z_score(value: float, mean: float, std: float) -> float:
    if std <= 1e-9:
        return 0.0
    return (value - mean) / std


def _day_distance(a: int, b: int) -> int:
    delta = abs(a - b)
    return min(delta, 366 - delta)


def seasonal_window(values: list[ObsDaily], target_day_of_year: int, width_days: int = 7) -> list[ObsDaily]:
    return [v for v in values if _day_distance(v.date.timetuple().tm_yday, target_day_of_year) <= width_days]


def compute_precip_streak(days: list[ObsDaily], until: date) -> int:
    streak = 0
    sorted_days = sorted([d for d in days if d.date <= until], key=lambda x: x.date, reverse=True)
    for day in sorted_days:
        if day.precip_sum is None or day.precip_sum <= 0.0:
            break
        streak += 1
    return streak


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))
