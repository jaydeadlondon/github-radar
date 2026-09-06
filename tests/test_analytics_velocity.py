from datetime import UTC, datetime

from analytics.series import build_daily_series
from analytics.velocity import (
    multi_window_velocity,
    regression_slope,
    window_velocity,
)


def _series(deltas):
    samples = []
    stars = 1000
    for i, delta in enumerate(deltas, start=1):
        stars += delta
        samples.append((datetime(2026, 8, i, 12, tzinfo=UTC), stars))
    return build_daily_series(samples)


def test_window_velocity_on_steady_growth():
    v = window_velocity(_series([10] * 10), 7)
    assert v is not None
    assert v.stars_per_day == 10.0
    assert v.stars_gained == 60  # span is 6 days between 7 points


def test_window_velocity_short_series_returns_none():
    assert window_velocity(_series([10]), 7) is None
    assert window_velocity([], 7) is None


def test_window_longer_than_series_uses_available_points():
    v = window_velocity(_series([5] * 4), 30)
    assert v is not None
    assert v.stars_per_day == 5.0


def test_regression_slope_on_perfect_line():
    slope = regression_slope(_series([10] * 10))
    assert slope is not None
    assert slope.slope == 10.0
    assert slope.r_squared == 1.0
    assert slope.n_points == 10


def test_regression_on_constant_series():
    slope = regression_slope(_series([0] * 5))
    assert slope.slope == 0.0
    assert slope.r_squared == 1.0


def test_regression_needs_two_points():
    assert regression_slope(_series([3])) is None


def test_multi_window_returns_result_per_window():
    results = multi_window_velocity(_series([7] * 10), windows=(7, 30))
    assert [r.window_days for r in results] == [7, 30]
    assert all(r.stars_per_day == 7.0 for r in results)


def test_multi_window_on_empty_series():
    assert multi_window_velocity([], windows=(7, 30)) == []
