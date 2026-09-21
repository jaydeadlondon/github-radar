from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from analytics.types import BurstEvent, DailyPoint, SlopeResult, VelocityResult

SERIES_COLUMNS: tuple[str, ...] = ("day", "stars", "delta")
LEADERBOARD_COLUMNS: tuple[str, ...] = (
    "rank",
    "owner",
    "name",
    "full_name",
    "language",
    "stars",
    "stars_per_day",
    "stars_gained",
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def series_rows(series: Sequence[DailyPoint]) -> list[dict[str, Any]]:
    return [
        {
            "day": point.day.isoformat(),
            "stars": point.stars,
            "delta": point.delta,
        }
        for point in series
    ]


def series_csv(series: Sequence[DailyPoint]) -> str:
    return rows_csv(SERIES_COLUMNS, series_rows(series))


def leaderboard_rows(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{column: item.get(column) for column in LEADERBOARD_COLUMNS} for item in items]


def leaderboard_csv(items: Iterable[dict[str, Any]]) -> str:
    return rows_csv(LEADERBOARD_COLUMNS, leaderboard_rows(items))


def rows_csv(columns: Sequence[str], rows: Iterable[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(columns),
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column) for column in columns})
    return output.getvalue()


def repository_payload(
    *,
    full_name: str,
    series: Sequence[DailyPoint],
    velocities: Sequence[VelocityResult],
    trend: SlopeResult | None,
    bursts: Sequence[BurstEvent],
    tracking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the versioned JSON shape used by CLI exports."""

    return {
        "format_version": "0.8",
        "repository": full_name,
        "series": series_rows(series),
        "velocity": [_json_value(item) for item in velocities],
        "trend": _json_value(trend) if trend is not None else None,
        "bursts": [_json_value(item) for item in bursts],
        "tracking": _json_value(tracking) if tracking is not None else None,
    }
