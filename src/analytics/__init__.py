from .bursts import detect_bursts
from .series import build_daily_series, tail
from .types import BurstEvent, DailyPoint, SlopeResult, VelocityResult
from .velocity import (
    multi_window_velocity,
    regression_slope,
    trend_summary,
    window_velocity,
)

__all__ = [
    "BurstEvent",
    "DailyPoint",
    "SlopeResult",
    "VelocityResult",
    "build_daily_series",
    "detect_bursts",
    "multi_window_velocity",
    "regression_slope",
    "tail",
    "trend_summary",
    "window_velocity",
]
