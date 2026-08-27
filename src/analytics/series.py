from __future__ import annotations
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta, timezone
from .types import DailyPoint

Sample = tuple[datetime, int]


def build_daily_series(samples: Iterable[Sample]) -> list[DailyPoint]:
    ordered = sorted(samples, key=lambda sample: sample[0])
    if not ordered:
        return []

    last_by_day: dict[date, int] = {}
    for recorded_at, stars in ordered:
        last_by_day[recorded_at.astimezone(timezone.utc).date()] = stars

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
