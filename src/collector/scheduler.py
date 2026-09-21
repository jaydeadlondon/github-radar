from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger(__name__)


def build_scheduler(
    settings: Settings,
    job: Callable[[], Awaitable[None]],
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        job,
        trigger=IntervalTrigger(hours=settings.scheduler_interval_hours),
        id="radar-snapshot",
        name="periodic snapshot of tracked repositories",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
        next_run_time=datetime.now(),
    )
    return scheduler


async def run_snapshot_job() -> None:
    from collector.jobs import execute_snapshot_job

    logger.info("snapshot job started")
    try:
        job_id = await execute_snapshot_job()
        logger.info("snapshot job finished job_id=%s", job_id)
    except Exception:
        logger.exception("snapshot job failed")
