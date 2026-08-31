from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .types import DailyPoint

MODES: tuple[str, ...] = ("absolute", "indexed", "percent")
INDEX_BASE = 100.0


@dataclass(frozen=True)
class ComparisonSeries:
    key: str
    values: list[float | None]


def day_grid(series_by_key: Mapping[str, Sequence[DailyPoint]]) -> list[date]:
    days = [point.day for series in series_by_key.values() for point in series]
    if not days:
        return []
    grid: list[date] = []
    day, end = min(days), max(days)
    while day <= end:
        grid.append(day)
        day += timedelta(days=1)
    return grid


def align_series(
    series_by_key: Mapping[str, Sequence[DailyPoint]],
) -> tuple[list[date], dict[str, list[int | None]]]:
    grid = day_grid(series_by_key)
    aligned: dict[str, list[int | None]] = {}
    for key, series in series_by_key.items():
        by_day = {point.day: point.stars for point in series}
        if not by_day:
            aligned[key] = [None] * len(grid)
            continue
        first, last = min(by_day), max(by_day)
        values: list[int | None] = []
        carried: int | None = None
        for day in grid:
            if day < first or day > last:
                values.append(None)
                continue
            carried = by_day.get(day, carried)
            values.append(carried)
        aligned[key] = values
    return grid, aligned


def _baseline(values: Sequence[int | None]) -> int | None:
    for value in values:
        if value is not None:
            return value
    return None


def normalize(values: Sequence[int | None], mode: str) -> list[float | None]:
    if mode not in MODES:
        raise ValueError(f"unknown comparison mode: {mode}")
    if mode == "absolute":
        return [None if value is None else float(value) for value in values]

    base = _baseline(values)
    if base is None:
        return [None] * len(values)
    base = max(base, 1)

    if mode == "indexed":
        return [
            None if value is None else round(value / base * INDEX_BASE, 2)
            for value in values
        ]
    return [
        None if value is None else round((value / base - 1) * 100, 2)
        for value in values
    ]


def build_comparison(
    series_by_key: Mapping[str, Sequence[DailyPoint]],
    *,
    mode: str = "absolute",
) -> tuple[list[date], list[ComparisonSeries]]:
    grid, aligned = align_series(series_by_key)
    comparison = [
        ComparisonSeries(key=key, values=normalize(values, mode))
        for key, values in aligned.items()
    ]
    return grid, comparison
