from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from alerts.runner import run_alert_evaluation
from config import settings
from data_quality import SnapshotQuality, sanitize_error
from db.base import SessionFactory
from db.jobs import release_lock, try_acquire_lock
from db.models import Repository
from db.repositories import create_snapshot, update_repository_metadata
from github.client import GitHubClient
from github.errors import GitHubError
from observability import metrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotRunResult:
    total_repositories: int
    succeeded_repositories: int
    failed_repositories: int
    skipped_repositories: int

    @property
    def saved(self) -> int:
        return self.succeeded_repositories


def _next_snapshot(moment: datetime) -> datetime:
    return moment + timedelta(hours=max(settings.scheduler_interval_hours, 1))


async def run_snapshot_result(
    repo_name: str | None = None,
    *,
    force: bool = False,
    owner_id: str | None = None,
) -> SnapshotRunResult:
    started = time.perf_counter()
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

    metrics.set_gauge("radar_tracked_repositories", len(repositories))
    if not repositories:
        metrics.observe(
            "radar_snapshot_duration_seconds",
            time.perf_counter() - started,
            labels={"result": "empty"},
        )
        return SnapshotRunResult(0, 0, 0, 0)

    lease_owner = owner_id or f"manual-{uuid4()}"
    saved = 0
    failed = 0
    skipped = 0
    updated_repo_ids: list[int] = []
    async with GitHubClient() as client:
        for repository in repositories:
            lock_name = f"snapshot:repository:{repository.id}"
            async with SessionFactory() as lock_session:
                acquired = await try_acquire_lock(
                    lock_session,
                    lock_name,
                    lease_owner,
                    ttl_seconds=settings.worker_lock_ttl_seconds,
                )
            if not acquired:
                skipped += 1
                logger.info(
                    "snapshot skipped",
                    extra={
                        "repository": repository.full_name,
                        "operation": "snapshot",
                        "result": "skipped",
                    },
                )
                continue

            try:
                observed_at = datetime.now(UTC)
                async with SessionFactory() as session:
                    repo = await session.get(Repository, repository.id)
                    if repo is None:
                        skipped += 1
                        continue
                    repo.last_snapshot_attempt_at = observed_at
                    repo.next_snapshot_at = _next_snapshot(observed_at)
                    await session.commit()

                try:
                    fresh = await client.get_repo(repository.full_name)
                except GitHubError as exc:
                    await _record_failure(repository.id, observed_at, exc)
                    failed += 1
                    metrics.increment("radar_snapshots", labels={"result": "failed"})
                    logger.warning(
                        "snapshot failed",
                        extra={
                            "repository": repository.full_name,
                            "operation": "fetch",
                            "result": "failed",
                            "error_category": type(exc).__name__,
                        },
                    )
                    continue
                except Exception as exc:
                    await _record_failure(repository.id, observed_at, exc)
                    failed += 1
                    metrics.increment("radar_snapshots", labels={"result": "failed"})
                    logger.warning(
                        "snapshot failed",
                        extra={
                            "repository": repository.full_name,
                            "operation": "fetch",
                            "result": "failed",
                            "error_category": type(exc).__name__,
                        },
                    )
                    continue

                async with SessionFactory() as session:
                    repo = await session.get(Repository, repository.id)
                    if repo is None:
                        skipped += 1
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
                            "snapshot rejected: "
                            f"{snapshot.quality_reason or 'quality check failed'}"
                        )
                        await session.commit()
                        failed += 1
                        metrics.increment(
                            "radar_snapshots", labels={"result": "failed"}
                        )
                        logger.warning(
                            "snapshot rejected",
                            extra={
                                "repository": repository.full_name,
                                "operation": "quality_check",
                                "result": "failed",
                                "error_category": "snapshot_quality",
                            },
                        )
                        continue
                    repo.last_successful_snapshot_at = observed_at
                    repo.last_snapshot_error = None
                    repo.next_snapshot_at = _next_snapshot(observed_at)
                    await session.commit()
                    saved += 1
                    metrics.increment("radar_snapshots", labels={"result": "succeeded"})
                    logger.info(
                        "snapshot saved",
                        extra={
                            "repository": repository.full_name,
                            "snapshot_id": snapshot.id,
                            "operation": "snapshot",
                            "result": "succeeded",
                        },
                    )
                    updated_repo_ids.append(repo.id)
            finally:
                async with SessionFactory() as lock_session:
                    await release_lock(lock_session, lock_name, lease_owner)

    if updated_repo_ids:
        try:
            await run_alert_evaluation(updated_repo_ids)
        except Exception:
            logger.exception("alert evaluation failed after snapshot collection")

    metrics.observe(
        "radar_snapshot_duration_seconds",
        time.perf_counter() - started,
        labels={"result": "completed" if failed == 0 else "partial"},
    )
    logger.info(
        "snapshot run complete",
        extra={
            "job_id": owner_id,
            "operation": "snapshot",
            "result": "completed" if failed == 0 else "partial",
        },
    )
    return SnapshotRunResult(
        total_repositories=len(repositories),
        succeeded_repositories=saved,
        failed_repositories=failed,
        skipped_repositories=skipped,
    )


async def run_snapshot(
    repo_name: str | None = None,
    *,
    force: bool = False,
) -> int:
    result = await run_snapshot_result(repo_name, force=force)
    return result.saved


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
