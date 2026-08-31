from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta

from .types import DailyPoint

Sample = tuple[datetime, int]


def as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def build_daily_series(samples: Iterable[Sample]) -> list[DailyPoint]:
    ordered = sorted(samples, key=lambda sample: as_utc(sample[0]))
    if not ordered:
        return []

    last_by_day: dict[date, int] = {}
    for recorded_at, stars in ordered:
        last_by_day[as_utc(recorded_at).date()] = stars

    series: list[DailyPoint] = []
    previous = last_by_day[min(last_by_day)]
    day = min(last_by_day)
    end = max(last_by_day)
    while day <= end:
        stars = last_by_day.get(day, previous)
        series.append(DailyPoint(day=day, stars=stars, delta=stars - previous))
        previous = stars
        day += timedelta(days=1)
    return series


def tail(series: Sequence[DailyPoint], days: int) -> list[DailyPoint]:
    if days <= 0:
        return []
    return list(series[-days:])


def moving_average(values: Sequence[float], window: int) -> list[float | None]:
    if window <= 1:
        return [float(value) for value in values]
    averages: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index + 1 < window:
            averages.append(None)
        else:
            averages.append(round(running / window, 2))
    return averages


def smooth_stars(series: Sequence[DailyPoint], window: int) -> list[float | None]:
    return moving_average([point.stars for point in series], window)


def smooth_deltas(series: Sequence[DailyPoint], window: int) -> list[float | None]:
    return moving_average([point.delta for point in series], window)
