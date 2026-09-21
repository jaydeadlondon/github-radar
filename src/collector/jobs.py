from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from collector.pipeline import run_snapshot_result
from config import settings
from data_quality import sanitize_error
from db.base import SessionFactory
from db.jobs import (
    create_snapshot_job,
    finish_snapshot_job,
    release_lock,
    renew_lock,
    try_acquire_lock,
)
from observability import metrics

logger = logging.getLogger(__name__)
GLOBAL_SNAPSHOT_LOCK = "snapshot:global"


async def _renew_global_lock(owner_id: str, stop: asyncio.Event) -> None:
    interval = max(settings.worker_lock_ttl_seconds // 3, 1)
    try:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                async with SessionFactory() as session:
                    renewed = await renew_lock(
                        session,
                        GLOBAL_SNAPSHOT_LOCK,
                        owner_id,
                        ttl_seconds=settings.worker_lock_ttl_seconds,
                    )
                if not renewed:
                    logger.error("snapshot global lock was lost owner=%s", owner_id)
                    return
    except asyncio.CancelledError:
        raise


async def execute_snapshot_job() -> str | None:
    """Run one globally locked snapshot job and persist its lifecycle."""

    job_id = str(uuid4())
    started = False
    async with SessionFactory() as session:
        acquired = await try_acquire_lock(
            session,
            GLOBAL_SNAPSHOT_LOCK,
            job_id,
            ttl_seconds=settings.worker_lock_ttl_seconds,
        )
        await create_snapshot_job(session, job_id)
        if not acquired:
            await finish_snapshot_job(
                session,
                job_id,
                status="skipped",
                error="another snapshot job is already running",
            )
            metrics.increment("snapshot_jobs", labels={"result": "skipped"})
            logger.info(
                "snapshot job skipped",
                extra={"job_id": job_id, "operation": "snapshot", "result": "skipped"},
            )
            return job_id
        started = True

    stop_renewal = asyncio.Event()
    renewal = asyncio.create_task(_renew_global_lock(job_id, stop_renewal))
    try:
        result = None
        last_error: BaseException | None = None
        attempts = max(settings.worker_retry_attempts, 0) + 1
        for attempt in range(attempts):
            try:
                result = await run_snapshot_result(owner_id=job_id)
                last_error = None
                break
            except Exception as exc:  # retry unexpected job-level failures
                last_error = exc
                if attempt >= attempts - 1:
                    break
                delay = min(
                    settings.worker_retry_backoff_seconds * (2**attempt),
                    settings.backoff_max,
                )
                logger.warning(
                    "snapshot job retry",
                    extra={
                        "job_id": job_id,
                        "operation": "snapshot",
                        "result": "retry",
                        "error_category": type(exc).__name__,
                    },
                )
                await asyncio.sleep(max(delay, 0))

        async with SessionFactory() as session:
            if last_error is not None or result is None:
                await finish_snapshot_job(
                    session,
                    job_id,
                    status="failed",
                    error=sanitize_error(last_error or RuntimeError("job produced no result")),
                )
                metrics.increment("snapshot_jobs", labels={"result": "failed"})
                logger.error(
                    "snapshot job failed",
                    extra={
                        "job_id": job_id,
                        "operation": "snapshot",
                        "result": "failed",
                        "error_category": type(last_error).__name__
                        if last_error is not None
                        else "unknown",
                    },
                )
            else:
                await finish_snapshot_job(
                    session,
                    job_id,
                    status="succeeded",
                    total_repositories=result.total_repositories,
                    succeeded_repositories=result.succeeded_repositories,
                    failed_repositories=(
                        result.failed_repositories + result.skipped_repositories
                    ),
                )
                metrics.increment("snapshot_jobs", labels={"result": "succeeded"})
                logger.info(
                    "snapshot job succeeded",
                    extra={"job_id": job_id, "operation": "snapshot", "result": "succeeded"},
                )
        return job_id
    finally:
        stop_renewal.set()
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        if started:
            async with SessionFactory() as session:
                await release_lock(session, GLOBAL_SNAPSHOT_LOCK, job_id)
