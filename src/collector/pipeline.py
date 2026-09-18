from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from alerts.runner import run_alert_evaluation
from config import settings
from data_quality import SnapshotQuality, sanitize_error
from db.base import SessionFactory
from db.models import Repository
from db.repositories import create_snapshot, update_repository_metadata
from github.client import GitHubClient
from github.errors import GitHubError

logger = logging.getLogger(__name__)


def _next_snapshot(moment: datetime) -> datetime:
    return moment + timedelta(hours=max(settings.scheduler_interval_hours, 1))


async def run_snapshot(
    repo_name: str | None = None,
    *,
    force: bool = False,
) -> int:
    """Collect quality-checked snapshots for active tracked repositories.

    Attempt state is committed before each network request and the result is
    committed per repository.  A failed repository therefore cannot roll back
    successful observations collected earlier in the same run.
    """

    async with SessionFactory() as session:
        stmt = select(Repository).order_by(Repository.id)
        if repo_name is not None:
            stmt = stmt.where(Repository.full_name == repo_name)
        elif not force:
            stmt = stmt.where(
                Repository.tracking_enabled.is_(True),
                Repository.tracking_paused.is_(False),
            )
        repositories = list((await session.scalars(stmt)).all())

    saved = 0
    updated_repo_ids: list[int] = []
    async with GitHubClient() as client:
        for repository in repositories:
            observed_at = datetime.now(UTC)
            async with SessionFactory() as session:
                repo = await session.get(Repository, repository.id)
                if repo is None:
                    continue
                repo.last_snapshot_attempt_at = observed_at
                repo.next_snapshot_at = _next_snapshot(observed_at)
                # Commit the attempt before calling GitHub.  This is important
                # when a process is interrupted during a slow request.
                await session.commit()

            try:
                fresh = await client.get_repo(repository.full_name)
            except GitHubError as exc:
                await _record_failure(repository.id, observed_at, exc)
                logger.warning("skipping %s: fetch failed", repository.full_name)
                continue
            except Exception as exc:  # defensive boundary around third-party transports
                await _record_failure(repository.id, observed_at, exc)
                logger.warning("skipping %s: fetch failed", repository.full_name)
                continue

            async with SessionFactory() as session:
                repo = await session.get(Repository, repository.id)
                if repo is None:
                    continue
                await update_repository_metadata(session, repo, fresh)
                snapshot = await create_snapshot(
                    session,
                    repo.id,
                    stargazers=fresh.stargazers_count,
                    forks=fresh.forks_count,
                    open_issues=fresh.open_issues_count,
                    observed_at=observed_at,
                )
                if snapshot.quality_status not in {
                    SnapshotQuality.ACCEPTED.value,
                    SnapshotQuality.ANOMALOUS.value,
                }:
                    repo.last_snapshot_error = sanitize_error(
                        f"snapshot rejected: {snapshot.quality_reason or 'quality check failed'}"
                    )
                    await session.commit()
                    logger.warning(
                        "skipping %s: snapshot rejected (%s)",
                        repository.full_name,
                        snapshot.quality_reason,
                    )
                    continue
                repo.last_successful_snapshot_at = observed_at
                repo.last_snapshot_error = None
                repo.next_snapshot_at = _next_snapshot(observed_at)
                await session.commit()
                saved += 1
                updated_repo_ids.append(repo.id)

    if updated_repo_ids:
        try:
            await run_alert_evaluation(updated_repo_ids)
        except Exception:
            logger.exception("alert evaluation failed after snapshot collection")

    return saved


async def _record_failure(
    repo_id: int,
    attempted_at: datetime,
    error: BaseException,
) -> None:
    async with SessionFactory() as session:
        repo = await session.get(Repository, repo_id)
        if repo is None:
            return
        repo.last_snapshot_attempt_at = attempted_at
        repo.next_snapshot_at = _next_snapshot(attempted_at)
        repo.last_snapshot_error = sanitize_error(error)
        await session.commit()
