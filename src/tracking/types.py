from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class TrackingStatus(StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    FAILED = "failed"
    PAUSED = "paused"
    UNTRACKED = "untracked"


@dataclass(frozen=True)
class TrackingState:
    tracking_enabled: bool
    tracking_paused: bool
    label: str | None
    status: TrackingStatus
    last_successful_snapshot_at: datetime | None
    last_snapshot_attempt_at: datetime | None
    last_snapshot_error: str | None
    snapshot_count: int
    history_start_at: datetime | None
    next_snapshot_at: datetime | None
    archived_at: datetime | None = None
    default_branch: str | None = None


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def tracking_status_for(
    *,
    tracking_enabled: bool,
    tracking_paused: bool,
    last_successful_snapshot_at: datetime | None,
    last_snapshot_attempt_at: datetime | None,
    last_snapshot_error: str | None,
    now: datetime,
    stale_after_seconds: float,
) -> TrackingStatus:
    if not tracking_enabled:
        return TrackingStatus.UNTRACKED
    if tracking_paused:
        return TrackingStatus.PAUSED

    attempt = as_utc(last_snapshot_attempt_at)
    success = as_utc(last_successful_snapshot_at)
    if last_snapshot_error and (
        success is None or attempt is None or attempt >= success
    ):
        return TrackingStatus.FAILED
    if success is None:
        return TrackingStatus.STALE

    current = as_utc(now) or datetime.now(UTC)
    age = (current - success).total_seconds()
    return TrackingStatus.STALE if age > stale_after_seconds else TrackingStatus.HEALTHY
