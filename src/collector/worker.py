from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterable

from collector.scheduler import build_scheduler, run_snapshot_job
from config import settings, validate_runtime_configuration
from logging_config import configure_logging

logger = logging.getLogger(__name__)


async def run_worker(
    *, once: bool = False, signals: Iterable[signal.Signals] | None = None
) -> None:
    validate_runtime_configuration()
    configure_logging(
        level=settings.log_level,
        json_logs=settings.log_format.lower() == "json",
    )
    if once:
        await run_snapshot_job()
        return

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled_signals = tuple(signals or (signal.SIGINT, signal.SIGTERM))
    for signum in handled_signals:
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):
            logger.debug("signal handler unavailable for %s", signum)

    scheduler = build_scheduler(settings, run_snapshot_job)
    scheduler.start()
    logger.info(
        "snapshot worker started (every %sh)",
        settings.scheduler_interval_hours,
    )
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        logger.info("snapshot worker stopped")
