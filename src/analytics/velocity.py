from __future__ import annotations
from collections.abc import Sequence
from datetime import timedelta
from .types import DailyPoint, VelocityResult

DEFAULT_WINDOWS: tuple[int, ...] = (7, 30, 90)


def window_velocity(
    series: Sequence[DailyPoint],
    window_days: int,
) -> VelocityResult | None:
    if window_days <= 0 or len(series) < 2:
        return None
    last = series[-1]
    start_boundary = last.day - timedelta(days=window_days - 1)
    points = [p for p in series if p.day >= start_boundary]
    if len(points) < 2:
        return None
    first = points[0]
    span = (last.day - first.day).days
    if span <= 0:
        return None
    gained = last.stars - first.stars
    return VelocityResult(
        window_days=window_days,
        stars_per_day=round(gained / span, 2),
        stars_gained=gained,
        start_day=first.day,
        end_day=last.day,
    )


def multi_window_velocity(
    series: Sequence[DailyPoint],
    windows: Sequence[int] = DEFAULT_WINDOWS,
) -> list[VelocityResult]:
    results: list[VelocityResult] = []
    for window_days in windows:
        result = window_velocity(series, window_days)
        if result is not None:
            results.append(result)
    return results
