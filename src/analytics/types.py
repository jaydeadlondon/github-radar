from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyPoint:
    day: date
    stars: int
    delta: int


@dataclass(frozen=True)
class VelocityResult:
    window_days: int
    stars_per_day: float
    stars_gained: int
    start_day: date
    end_day: date


@dataclass(frozen=True)
class SlopeResult:
    slope: float
    intercept: float
    r_squared: float
    n_points: int


@dataclass(frozen=True)
class BurstEvent:
    start_day: date
    end_day: date
    duration_days: int
    peak_day: date
    peak_delta: int
    total_gained: int
    severity: float
