from datetime import UTC, datetime

from analytics.series import build_daily_series, tail


def _dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


def test_empty_input_returns_empty_series():
    assert build_daily_series([]) == []


def test_single_sample_yields_one_point_with_zero_delta():
    series = build_daily_series([(_dt(1), 100)])
    assert len(series) == 1
    assert series[0].stars == 100
    assert series[0].delta == 0


def test_last_sample_of_the_day_wins():
    series = build_daily_series([(_dt(1, 8), 100), (_dt(1, 22), 105), (_dt(2), 110)])
    assert [p.stars for p in series] == [105, 110]


def test_missing_day_is_filled_with_zero_delta():
    series = build_daily_series([(_dt(1), 100), (_dt(3), 120)])
    assert [(p.day.day, p.stars, p.delta) for p in series] == [
        (1, 100, 0),
        (2, 100, 0),
        (3, 120, 20),
    ]


def test_unsorted_input_is_handled():
    series = build_daily_series([(_dt(3), 120), (_dt(1), 100), (_dt(2), 110)])
    assert [p.stars for p in series] == [100, 110, 120]


def test_tail_returns_last_n_points():
    series = build_daily_series([(_dt(d), 100 + 10 * d) for d in (1, 2, 3, 4)])
    assert len(tail(series, 2)) == 2
    assert tail(series, 2)[-1].stars == 140
    assert tail(series, 0) == []
