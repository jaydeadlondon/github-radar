from datetime import UTC, date, datetime, timedelta

from analytics.bursts import detect_bursts, flag_burst_days, group_flagged_days
from analytics.series import as_utc, build_daily_series, tail
from analytics.velocity import (
    multi_window_velocity,
    regression_slope,
    trend_summary,
    window_velocity,
)

DAY = timedelta(days=1)
START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _samples(values: list[int], *, aware: bool = True) -> list[tuple[datetime, int]]:
    base = START if aware else START.replace(tzinfo=None)
    return [(base + index * DAY, stars) for index, stars in enumerate(values)]


def test_as_utc_assumes_utc_for_naive_timestamps() -> None:
    naive = datetime(2026, 8, 30, 23, 30)
    assert as_utc(naive) == datetime(2026, 8, 30, 23, 30, tzinfo=UTC)
    assert as_utc(naive).date() == date(2026, 8, 30)


def test_build_daily_series_computes_deltas() -> None:
    series = build_daily_series(_samples([100, 110, 125]))

    assert [point.day for point in series] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert [point.stars for point in series] == [100, 110, 125]
    assert [point.delta for point in series] == [0, 10, 15]


def test_build_daily_series_fills_gaps_and_keeps_last_value_per_day() -> None:
    samples = [
        (START, 100),
        (START + timedelta(hours=6), 105),  # same day, later reading wins
        (START + 3 * DAY, 130),  # two missing days in between
    ]

    series = build_daily_series(samples)

    assert [(point.day.day, point.stars, point.delta) for point in series] == [
        (1, 105, 0),
        (2, 105, 0),
        (3, 105, 0),
        (4, 130, 25),
    ]


def test_build_daily_series_handles_naive_timestamps_like_sqlite_returns() -> None:
    naive = build_daily_series(_samples([100, 150], aware=False))
    aware = build_daily_series(_samples([100, 150]))

    assert [(p.day, p.stars, p.delta) for p in naive] == [
        (p.day, p.stars, p.delta) for p in aware
    ]


def test_build_daily_series_is_empty_without_samples() -> None:
    assert build_daily_series([]) == []


def test_tail_returns_the_last_days_only() -> None:
    series = build_daily_series(_samples([1, 2, 3, 4, 5]))

    assert [point.stars for point in tail(series, 2)] == [4, 5]
    assert tail(series, 0) == []


def test_window_velocity_uses_the_actual_span() -> None:
    series = build_daily_series(_samples([100, 110, 120, 130]))

    result = window_velocity(series, 3)

    assert result is not None
    assert result.window_days == 3
    assert result.stars_gained == 20
    assert result.stars_per_day == 10.0
    assert (result.start_day, result.end_day) == (date(2026, 1, 2), date(2026, 1, 4))


def test_window_velocity_needs_at_least_two_points() -> None:
    assert window_velocity(build_daily_series(_samples([100])), 7) is None
    assert window_velocity([], 7) is None
    assert window_velocity(build_daily_series(_samples([1, 2])), 0) is None


def test_multi_window_velocity_skips_windows_without_data() -> None:
    series = build_daily_series(_samples([100, 130]))

    results = multi_window_velocity(series, (7, 30, 90))

    assert [item.window_days for item in results] == [7, 30, 90]
    assert {item.stars_gained for item in results} == {30}


def test_regression_slope_fits_a_straight_line() -> None:
    series = build_daily_series(_samples([100, 110, 120, 130]))

    slope = regression_slope(series)

    assert slope is not None
    assert slope.slope == 10.0
    assert slope.intercept == 100.0
    assert slope.r_squared == 1.0
    assert slope.n_points == 4


def test_regression_slope_reports_a_weak_fit_for_noisy_data() -> None:
    slope = regression_slope(build_daily_series(_samples([100, 400, 120, 380, 140])))

    assert slope is not None
    assert slope.r_squared < 0.5


def test_regression_slope_needs_two_points() -> None:
    assert regression_slope(build_daily_series(_samples([100]))) is None


def test_trend_summary_only_looks_at_the_requested_window() -> None:
    series = build_daily_series(_samples([100, 100, 100, 200, 300]))

    trend = trend_summary(series, 2)

    assert trend is not None
    assert trend.n_points == 2
    assert trend.slope == 100.0


def test_flag_burst_days_ignores_the_warmup_period() -> None:
    series = build_daily_series(_samples([100, 200, 300, 400, 500]))

    assert flag_burst_days(series) == []


def test_detect_bursts_finds_a_spike_over_a_quiet_baseline() -> None:
    quiet = [100 + step for step in range(0, 20)]
    spike = [quiet[-1] + 200, quiet[-1] + 400]
    series = build_daily_series(_samples(quiet + spike))

    events = detect_bursts(series)

    assert len(events) == 1
    event = events[0]
    assert event.duration_days == 2
    assert event.peak_delta == 200
    assert event.total_gained == 400
    assert event.severity > 1
    assert event.end_day == series[-1].day


def test_detect_bursts_respects_the_minimum_duration() -> None:
    quiet = [100 + step for step in range(0, 20)]
    series = build_daily_series(_samples([*quiet, quiet[-1] + 200]))

    assert detect_bursts(series) == []
    assert len(detect_bursts(series, min_duration=1)) == 1


def test_detect_bursts_ignores_small_absolute_deltas() -> None:
    series = build_daily_series(_samples([*(100 for _ in range(20)), 103]))

    assert detect_bursts(series, min_duration=1) == []
    assert detect_bursts(series, min_duration=1, min_delta=3)


def test_group_flagged_days_splits_non_consecutive_runs() -> None:
    quiet = [100 for _ in range(20)]
    growth = [200, 400, 400, 600, 800]
    series = build_daily_series(_samples(quiet + growth))

    flags = flag_burst_days(series)
    events = group_flagged_days(flags, min_duration=1)

    assert len(events) == 2
    assert events[0].end_day < events[1].start_day
