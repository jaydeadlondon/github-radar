from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from analytics import service
from api.deps import get_session
from api.schemas import (
    BurstOut,
    BurstsOut,
    LeaderboardItemOut,
    Paginated,
    RepoBriefOut,
    RepoSeriesOut,
    RepoVelocityOut,
    SeriesPointOut,
    SlopeOut,
    VelocityOut,
)
from config import settings
from db.models import Repository
from db.repositories import get_repository_by_name

router = APIRouter(prefix="/analytics", tags=["analytics"])

MAX_WINDOWS = 5


def _parse_windows(raw: str) -> list[int]:
    try:
        values = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="windows must be a comma-separated list of integers",
        ) from exc
    if not values or len(values) > MAX_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"provide between 1 and {MAX_WINDOWS} windows",
        )
    if any(value < 1 or value > 365 for value in values):
        raise HTTPException(
            status_code=422,
            detail="each window must be between 1 and 365 days",
        )
    return values


@router.get("/velocity/{owner}/{name}", response_model=RepoVelocityOut)
async def get_velocity(
    owner: str,
    name: str,
    windows: str = "7,30,90",
    days: int | None = Query(default=None, ge=7, le=365),
    session: AsyncSession = Depends(get_session),
) -> RepoVelocityOut:
    window_list = _parse_windows(windows)
    repo = await _load_repo(session, owner, name)

    velocities, trend, latest_stars = await service.repo_velocity(
        session,
        repo.id,
        windows=window_list,
        history_days=days or settings.analytics_history_days,
    )

    owner_part, _, name_part = repo.full_name.partition("/")
    return RepoVelocityOut(
        repo=RepoBriefOut(
            owner=owner_part,
            name=name_part,
            full_name=repo.full_name,
            stars=latest_stars or 0,
        ),
        velocities=[
            VelocityOut.model_validate(v, from_attributes=True) for v in velocities
        ],
        trend=SlopeOut.model_validate(trend, from_attributes=True) if trend else None,
    )


async def _load_repo(session: AsyncSession, owner: str, name: str) -> Repository:
    full_name = f"{owner}/{name}"
    repo = await get_repository_by_name(session, full_name)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"repository {full_name} not found")
    return repo


@router.get("/series/{owner}/{name}", response_model=RepoSeriesOut)
async def get_series(
    owner: str,
    name: str,
    days: int | None = Query(default=None, ge=7, le=365),
    smooth: int = Query(default=0, ge=0, le=90, description="Moving-average window"),
    session: AsyncSession = Depends(get_session),
) -> RepoSeriesOut:
    repo = await _load_repo(session, owner, name)
    series, stars_avg, delta_avg = await service.repo_smoothed_series(
        session,
        repo.id,
        history_days=days or settings.analytics_history_days,
        smooth_window=smooth,
    )

    owner_part, _, name_part = repo.full_name.partition("/")
    return RepoSeriesOut(
        repo=RepoBriefOut(
            owner=owner_part,
            name=name_part,
            full_name=repo.full_name,
            stars=series[-1].stars if series else 0,
        ),
        smooth_window=smooth,
        points=[
            SeriesPointOut(
                day=point.day,
                stars=point.stars,
                delta=point.delta,
                stars_avg=stars_avg[index],
                delta_avg=delta_avg[index],
            )
            for index, point in enumerate(series)
        ],
    )


@router.get("/bursts/{owner}/{name}", response_model=BurstsOut)
async def get_bursts(
    owner: str,
    name: str,
    days: int | None = Query(default=None, ge=7, le=365),
    session: AsyncSession = Depends(get_session),
) -> BurstsOut:
    repo = await _load_repo(session, owner, name)

    events, active = await service.repo_bursts(
        session,
        repo.id,
        history_days=days or settings.analytics_history_days,
        rolling_window=settings.analytics_rolling_window,
        z_threshold=settings.analytics_burst_z,
        min_delta=settings.analytics_burst_min_delta,
        min_duration=settings.analytics_burst_min_days,
    )
    return BurstsOut(
        items=[BurstOut.model_validate(e, from_attributes=True) for e in events],
        active_burst=active,
    )


LEADERBOARD_WINDOWS = (7, 30, 90)


@router.get("/leaderboard", response_model=Paginated[LeaderboardItemOut])
async def get_leaderboard(
    window: int = Query(default=7),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[LeaderboardItemOut]:
    if window not in LEADERBOARD_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail="window must be one of 7, 30, 90",
        )
    total, scored = await service.leaderboard(
        session, window_days=window, limit=limit, offset=offset
    )
    items: list[LeaderboardItemOut] = []
    for index, (repo, velocity, stars) in enumerate(scored):
        owner, _, name = repo.full_name.partition("/")
        items.append(
            LeaderboardItemOut(
                rank=offset + index + 1,
                owner=owner,
                name=name,
                full_name=repo.full_name,
                language=repo.language,
                stars=stars,
                stars_per_day=velocity.stars_per_day,
                stars_gained=velocity.stars_gained,
            )
        )
    return Paginated(
        total=total,
        offset=offset,
        limit=limit,
        next_offset=offset + len(items) if offset + len(items) < total else None,
        items=items,
    )
