from datetime import date, timedelta

import pytest

from analytics.compare import (
    align_series,
    build_comparison,
    day_grid,
    normalize,
)
from analytics.series import moving_average, smooth_deltas, smooth_stars
from analytics.types import DailyPoint

DAY = timedelta(days=1)
START = date(2026, 1, 1)


def _series(values: list[int], *, offset: int = 0) -> list[DailyPoint]:
    points: list[DailyPoint] = []
    previous = values[0] if values else 0
    for index, stars in enumerate(values):
        points.append(
            DailyPoint(
                day=START + (index + offset) * DAY, stars=stars, delta=stars - previous
            )
        )
        previous = stars
    return points


def test_moving_average_leaves_the_warmup_empty() -> None:
    assert moving_average([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_moving_average_with_window_one_returns_the_values() -> None:
    assert moving_average([1, 2, 3], 1) == [1.0, 2.0, 3.0]
    assert moving_average([], 7) == []


def test_smooth_helpers_work_on_stars_and_deltas() -> None:
    series = _series([100, 110, 130, 160])

    assert smooth_stars(series, 2) == [None, 105.0, 120.0, 145.0]
    assert smooth_deltas(series, 2) == [None, 5.0, 15.0, 25.0]


def test_day_grid_spans_every_series() -> None:
    grid = day_grid({"a": _series([1, 2]), "b": _series([1, 2], offset=3)})

    assert grid == [START + index * DAY for index in range(5)]
    assert day_grid({}) == []


def test_align_series_forward_fills_inside_its_own_range() -> None:
    a = [DailyPoint(START, 100, 0), DailyPoint(START + 3 * DAY, 130, 30)]
    b = [DailyPoint(START + 1 * DAY, 50, 0), DailyPoint(START + 2 * DAY, 60, 10)]

    grid, aligned = align_series({"a": a, "b": b})

    assert len(grid) == 4
    assert aligned["a"] == [100, 100, 100, 130]
    assert aligned["b"] == [None, 50, 60, None]


def test_align_series_handles_an_empty_series() -> None:
    grid, aligned = align_series({"a": _series([1, 2]), "b": []})

    assert aligned["b"] == [None] * len(grid)


def test_normalize_absolute_keeps_the_values() -> None:
    assert normalize([100, None, 130], "absolute") == [100.0, None, 130.0]


def test_normalize_indexed_starts_at_one_hundred() -> None:
    assert normalize([200, 220, 260], "indexed") == [100.0, 110.0, 130.0]


def test_normalize_percent_reports_growth_from_the_start() -> None:
    assert normalize([200, 220, 260], "percent") == [0.0, 10.0, 30.0]


def test_normalize_skips_leading_gaps_when_picking_a_baseline() -> None:
    assert normalize([None, 50, 75], "percent") == [None, 0.0, 50.0]


def test_normalize_survives_a_zero_baseline() -> None:
    assert normalize([0, 1], "indexed") == [0.0, 100.0]


def test_normalize_returns_gaps_for_an_empty_series() -> None:
    assert normalize([None, None], "indexed") == [None, None]


def test_normalize_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown comparison mode"):
        normalize([1, 2], "logarithmic")


def test_build_comparison_returns_grid_and_rebased_series() -> None:
    faster = _series([100, 150, 200])
    slower = _series([1000, 1010, 1020])

    days, comparison = build_comparison({"a": faster, "b": slower}, mode="percent")

    assert days == [START, START + DAY, START + 2 * DAY]
    by_key = {item.key: item.values for item in comparison}
    assert by_key["a"] == [0.0, 50.0, 100.0]
    assert by_key["b"] == [0.0, 1.0, 2.0]


def test_build_comparison_is_empty_without_series() -> None:
    assert build_comparison({}) == ([], [])
