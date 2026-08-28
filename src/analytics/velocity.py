from __future__ import annotations
from collections.abc import Sequence
from datetime import timedelta
from .series import tail
from .types import DailyPoint, SlopeResult, VelocityResult

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


def regression_slope(series: Sequence[DailyPoint]) -> SlopeResult | None:
    n = len(series)
    if n < 2:
        return None
    xs = list(range(n))
    ys = [point.stars for point in series]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    sxx = sum((x - x_mean) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean

    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot == 0:
        r_squared = 1.0 if slope == 0 else 0.0
    else:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        r_squared = 1 - ss_res / ss_tot

    return SlopeResult(
        slope=round(slope, 4),
        intercept=round(intercept, 4),
        r_squared=round(max(0.0, min(1.0, r_squared)), 4),
        n_points=n,
    )


def trend_summary(
    series: Sequence[DailyPoint],
    window_days: int,
) -> SlopeResult | None:
    return regression_slope(tail(series, window_days))
