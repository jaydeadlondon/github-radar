from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import sqrt
from .types import DailyPoint

DEFAULT_ROLLING_WINDOW = 14
DEFAULT_Z = 2.5
DEFAULT_MIN_DELTA = 5
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
