from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analytics.bursts import detect_bursts
from analytics.series import (
    Sample,
    build_daily_series,
    smooth_deltas,
    smooth_stars,
)
from analytics.types import BurstEvent, DailyPoint, SlopeResult, VelocityResult
from analytics.velocity import multi_window_velocity, trend_summary, window_velocity
from db.models import Repository, RepoSnapshot
from db.repositories import fetch_histories


def _to_samples(snapshots: Sequence[RepoSnapshot]) -> list[Sample]:
    return [(s.observed_at, s.stargazers_count) for s in snapshots]


def _since(history_days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=history_days)


async def repo_series(
    session: AsyncSession,
    repo_id: int,
    *,
    history_days: int,
) -> list[DailyPoint]:
    histories = await fetch_histories(session, [repo_id], since=_since(history_days))
    return build_daily_series(_to_samples(histories.get(repo_id, [])))


async def repo_smoothed_series(
    session: AsyncSession,
    repo_id: int,
    *,
    history_days: int,
    smooth_window: int = 0,
) -> tuple[list[DailyPoint], list[float | None], list[float | None]]:
    series = await repo_series(session, repo_id, history_days=history_days)
    if smooth_window <= 1 or not series:
        empty: list[float | None] = [None] * len(series)
        return series, empty, list(empty)
    return (
        series,
        smooth_stars(series, smooth_window),
        smooth_deltas(series, smooth_window),
    )


async def repo_velocity(
    session: AsyncSession,
    repo_id: int,
    *,
    windows: Sequence[int] = (7, 30, 90),
    history_days: int,
) -> tuple[list[VelocityResult], SlopeResult | None, int | None]:
    series = await repo_series(session, repo_id, history_days=history_days)
    velocities = multi_window_velocity(series, windows)
    trend = trend_summary(series, history_days) if len(series) >= 2 else None
    latest_stars = series[-1].stars if series else None
    return velocities, trend, latest_stars


async def repo_bursts(
    session: AsyncSession,
    repo_id: int,
    *,
    history_days: int,
    rolling_window: int,
    z_threshold: float,
    min_delta: int,
    min_duration: int,
) -> tuple[list[BurstEvent], bool]:
    series = await repo_series(session, repo_id, history_days=history_days)
    events = detect_bursts(
        series,
        rolling_window=rolling_window,
        z_threshold=z_threshold,
        min_delta=min_delta,
        min_duration=min_duration,
    )
    active = bool(events and series and (series[-1].day - events[-1].end_day).days <= 2)
    return events, active


async def leaderboard(
    session: AsyncSession,
    *,
    window_days: int,
    limit: int,
    offset: int,
) -> tuple[int, list[tuple[Repository, VelocityResult, int]]]:
    repos = list((await session.execute(select(Repository))).scalars())
    if not repos:
        return 0, []
    since = datetime.now(UTC) - timedelta(days=window_days + 1)
    histories = await fetch_histories(session, [r.id for r in repos], since=since)

    scored: list[tuple[Repository, VelocityResult, int]] = []
    for repo in repos:
        snapshots = histories.get(repo.id, [])
        series = build_daily_series(_to_samples(snapshots))
        velocity = window_velocity(series, window_days)
        if velocity is not None:
            scored.append((repo, velocity, snapshots[-1].stargazers_count))

    scored.sort(key=lambda item: item[1].stars_per_day, reverse=True)
    total = len(scored)
    return total, scored[offset : offset + limit]
