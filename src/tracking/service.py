from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import Repository
from db.repositories import get_repository_by_name, snapshot_stats
from tracking.types import TrackingState, as_utc, tracking_status_for


class TrackingError(ValueError):
    """A user-correctable tracking operation error."""


class RepositoryNotKnownError(TrackingError):
    """Raised when an operation needs a repository that is not in the database."""


def stale_after_seconds() -> float:
    configured = getattr(settings, "tracking_stale_after_hours", None)
    hours = configured if configured is not None else max(settings.scheduler_interval_hours * 2, 1)
    return max(float(hours), 1.0) * 60 * 60


def _now(value: datetime | None = None) -> datetime:
    return as_utc(value) or datetime.now(UTC)


async def tracking_state(
    session: AsyncSession,
    repository: Repository,
    *,
    now: datetime | None = None,
) -> TrackingState:
    count, first = await snapshot_stats(session, repository.id)
    current = _now(now)
    status = tracking_status_for(
        tracking_enabled=repository.tracking_enabled,
        tracking_paused=repository.tracking_paused,
        last_successful_snapshot_at=repository.last_successful_snapshot_at,
        last_snapshot_attempt_at=repository.last_snapshot_attempt_at,
        last_snapshot_error=repository.last_snapshot_error,
        now=current,
        stale_after_seconds=stale_after_seconds(),
    )
    next_snapshot = as_utc(repository.next_snapshot_at)
    if next_snapshot is None and repository.last_successful_snapshot_at is not None:
        next_snapshot = as_utc(repository.last_successful_snapshot_at) + timedelta(
            hours=max(settings.scheduler_interval_hours, 1)
        )
    return TrackingState(
        tracking_enabled=repository.tracking_enabled,
        tracking_paused=repository.tracking_paused,
        label=repository.tracking_label,
        status=status,
        last_successful_snapshot_at=as_utc(repository.last_successful_snapshot_at),
        last_snapshot_attempt_at=as_utc(repository.last_snapshot_attempt_at),
        last_snapshot_error=repository.last_snapshot_error,
        snapshot_count=count,
        history_start_at=as_utc(first),
        next_snapshot_at=next_snapshot,
        archived_at=as_utc(repository.archived_at),
        default_branch=repository.default_branch,
    )


async def known_repository(
    session: AsyncSession,
    full_name: str,
) -> Repository:
    repository = await get_repository_by_name(session, full_name)
    if repository is None:
        raise RepositoryNotKnownError(f"repository {full_name} is not known")
    return repository


async def track(
    session: AsyncSession,
    repository: Repository,
    *,
    label: str | None = None,
    now: datetime | None = None,
) -> Repository:
    repository.tracking_enabled = True
    repository.tracking_paused = False
    if label is not None:
        repository.tracking_label = label.strip() or None
    if repository.next_snapshot_at is None:
        repository.next_snapshot_at = _now(now)
    await session.flush()
    return repository


async def untrack(
    session: AsyncSession,
    repository: Repository,
    *,
    now: datetime | None = None,
) -> Repository:
    """Remove a repository from active tracking without deleting any history."""

    repository.tracking_enabled = False
    repository.tracking_paused = False
    repository.next_snapshot_at = None
    await session.flush()
    return repository


async def pause(
    session: AsyncSession,
    repository: Repository,
) -> Repository:
    repository.tracking_enabled = True
    repository.tracking_paused = True
    await session.flush()
    return repository


async def resume(
    session: AsyncSession,
    repository: Repository,
    *,
    now: datetime | None = None,
) -> Repository:
    repository.tracking_enabled = True
    repository.tracking_paused = False
    repository.next_snapshot_at = _now(now)
    await session.flush()
    return repository


async def set_label(
    session: AsyncSession,
    repository: Repository,
    label: str | None,
) -> Repository:
    repository.tracking_label = label.strip() or None if label is not None else None
    await session.flush()
    return repository


async def states_for(
    session: AsyncSession,
    repositories: Iterable[Repository],
    *,
    now: datetime | None = None,
) -> dict[int, TrackingState]:
    return {
        repository.id: await tracking_state(session, repository, now=now)
        for repository in repositories
    }


__all__ = [
    "RepositoryNotKnownError",
    "TrackingError",
    "known_repository",
    "pause",
    "resume",
    "set_label",
    "stale_after_seconds",
    "states_for",
    "track",
    "tracking_state",
    "untrack",
]
