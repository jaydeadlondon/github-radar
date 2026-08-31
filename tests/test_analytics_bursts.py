from datetime import datetime, timedelta, timezone

from analytics.bursts import detect_bursts, flag_burst_days
from analytics.series import build_daily_series


def _series(deltas):
    base = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    samples = []
    stars = 1000
    for i, delta in enumerate(deltas):
        stars += delta
        samples.append((base + timedelta(days=i), stars))
    return build_daily_series(samples)


def test_flat_series_has_no_bursts():
    assert detect_bursts(_series([2] * 40)) == []


def test_spike_is_detected_as_single_event():
    events = detect_bursts(_series([2] * 30 + [40] * 5 + [2] * 5))
    assert len(events) == 1
    ev = events[0]
    assert ev.duration_days == 5
    assert ev.peak_delta == 40
    assert ev.total_gained == 200
    assert ev.severity > 1


def test_min_duration_filters_single_day_flags():
    assert detect_bursts(_series([2] * 30 + [50] + [2] * 5), min_duration=2) == []


def test_higher_z_threshold_suppresses_detection():
    deltas = [2] * 30 + [12] * 3 + [2] * 5
    assert detect_bursts(_series(deltas), z_threshold=2.5) != []
    assert detect_bursts(_series(deltas), z_threshold=50) == []


def test_min_delta_filters_micro_spikes():
    events = detect_bursts(_series([0] * 30 + [3, 3] + [0] * 5), min_delta=5)
    assert events == []


def test_two_spikes_far_apart_are_two_events():
    deltas = [2] * 30 + [40, 40] + [2] * 14 + [40, 40] + [2] * 5
    events = detect_bursts(_series(deltas), min_duration=2)
    assert len(events) == 2
    assert events[0].start_day < events[1].start_day
    assert all(e.duration_days == 2 for e in events)


def test_flagged_days_need_history():
    flags = flag_burst_days(_series([2, 2, 100]))
    assert flags == []
