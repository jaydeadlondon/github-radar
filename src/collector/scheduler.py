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
    from collector.pipeline import run_snapshot

    logger.info("snapshot run started")
    try:
        saved = await run_snapshot()
        logger.info("snapshot run finished (%s repository(-ies) updated)", saved)
    except Exception:
        logger.exception("snapshot run failed")
