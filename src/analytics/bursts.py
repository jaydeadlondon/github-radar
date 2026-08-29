from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import sqrt

from .types import BurstEvent, DailyPoint

DEFAULT_ROLLING_WINDOW = 14
DEFAULT_Z = 2.5
DEFAULT_MIN_DELTA = 5
DEFAULT_MIN_DURATION = 2
MIN_HISTORY = 5
FLOOR_STD = 1.0


@dataclass(frozen=True)
class FlaggedDay:
    day: date
    delta: int
    mean: float
    std: float
    z: float


def flag_burst_days(
    series: Sequence[DailyPoint],
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    z_threshold: float = DEFAULT_Z,
    min_delta: int = DEFAULT_MIN_DELTA,
) -> list[FlaggedDay]:
    flagged: list[FlaggedDay] = []
    baseline: list[int] = []
    for point in series:
        if len(baseline) >= MIN_HISTORY:
            window = baseline[-rolling_window:]
            mean = sum(window) / len(window)
            variance = sum((d - mean) ** 2 for d in window) / len(window)
            std = max(sqrt(variance), FLOOR_STD)
            z = (point.delta - mean) / std
            if z >= z_threshold and point.delta >= min_delta:
                flagged.append(
                    FlaggedDay(
                        day=point.day,
                        delta=point.delta,
                        mean=mean,
                        std=std,
                        z=z,
                    )
                )
                continue
        baseline.append(point.delta)
    return flagged


def group_flagged_days(
    flags: Sequence[FlaggedDay],
    *,
    min_duration: int = DEFAULT_MIN_DURATION,
) -> list[BurstEvent]:
    events: list[BurstEvent] = []
    run: list[FlaggedDay] = []
    for flag in flags:
        if run and (flag.day - run[-1].day).days == 1:
            run.append(flag)
        else:
            event = _make_event(run, min_duration)
            if event is not None:
                events.append(event)
            run = [flag]
    event = _make_event(run, min_duration)
    if event is not None:
        events.append(event)
    return events


def _make_event(
    run: Sequence[FlaggedDay],
    min_duration: int,
) -> BurstEvent | None:
    if len(run) < min_duration:
        return None
    peak = max(run, key=lambda flag: flag.delta)
    return BurstEvent(
        start_day=run[0].day,
        end_day=run[-1].day,
        duration_days=len(run),
        peak_day=peak.day,
        peak_delta=peak.delta,
        total_gained=sum(flag.delta for flag in run),
        severity=round(peak.delta / max(peak.mean, 1.0), 2),
    )


def detect_bursts(
    series: Sequence[DailyPoint],
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    z_threshold: float = DEFAULT_Z,
    min_delta: int = DEFAULT_MIN_DELTA,
    min_duration: int = DEFAULT_MIN_DURATION,
) -> list[BurstEvent]:
    flags = flag_burst_days(
        series,
        rolling_window=rolling_window,
        z_threshold=z_threshold,
        min_delta=min_delta,
    )
    return group_flagged_days(flags, min_duration=min_duration)
