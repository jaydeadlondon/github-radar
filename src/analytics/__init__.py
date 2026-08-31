from .bursts import detect_bursts
from .compare import (
    ComparisonSeries,
    align_series,
    build_comparison,
    day_grid,
    normalize,
)
from .series import (
    as_utc,
    build_daily_series,
    tail,
)
from .types import BurstEvent, DailyPoint, SlopeResult, VelocityResult
from .velocity import (
    multi_window_velocity,
    regression_slope,
    trend_summary,
    window_velocity,
)

__all__ = [
    "BurstEvent",
    "ComparisonSeries",
    "DailyPoint",
    "SlopeResult",
    "VelocityResult",
    "align_series",
    "as_utc",
    "build_comparison",
    "build_daily_series",
    "day_grid",
    "detect_bursts",
    "multi_window_velocity",
    "normalize",
    "regression_slope",
    "tail",
    "trend_summary",
    "window_velocity",
]
