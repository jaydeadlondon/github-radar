from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from analytics import service
from api.deps import (
    get_repo_or_404,
    get_session,
    require_admin_api_key,
    require_read_api_key,
)
from api.schemas import (
    Paginated,
    RepoDetailOut,
    RepoOut,
    TrackingStatusOut,
    TrackingTrackIn,
    TrackingUpdate,
    VelocityOut,
)
from config import settings
from db.models import Repository
from db.repositories import (
    get_latest_snapshot,
    get_repository_by_name,
    list_repositories,
    upsert_repository,
)
from github.client import GitHubClient
from github.errors import GitHubError, NotFoundError
from tracking.service import pause, resume, set_label, track, tracking_state, untrack
from tracking.types import TrackingState, as_utc

router = APIRouter(
    prefix="/repos",
    tags=["repos"],
    dependencies=[Depends(require_read_api_key)],
)
TrackingFilter = Literal["tracked", "active", "paused", "untracked", "all"]
TrackingStatusFilter = Literal["healthy", "stale", "failed", "paused", "untracked"]


def _tracking_out(repository: Repository, state: TrackingState) -> TrackingStatusOut:
    return TrackingStatusOut(
        id=repository.id,
        repository=repository.full_name,
        tracking_enabled=state.tracking_enabled,
        tracking_paused=state.tracking_paused,
        label=state.label,
        tracking_label=state.label,
        status=state.status.value,
        tracking_status=state.status.value,
        last_successful_snapshot_at=as_utc(state.last_successful_snapshot_at),
        last_snapshot_attempt_at=as_utc(state.last_snapshot_attempt_at),
        last_snapshot_error=state.last_snapshot_error,
        snapshot_count=state.snapshot_count,
        history_start_at=as_utc(state.history_start_at),
        next_snapshot_at=as_utc(state.next_snapshot_at),
        archived_at=as_utc(state.archived_at),
        default_branch=state.default_branch,
    )


async def _to_out(session: AsyncSession, repo: Repository) -> RepoOut:
    state = await tracking_state(session, repo)
    return RepoOut(
        id=repo.id,
        full_name=repo.full_name,
        description=repo.description,
        html_url=repo.html_url,
        language=repo.language,
        stargazers_count=repo.latest_stargazers,
        forks_count=repo.latest_forks,
        tracking_enabled=state.tracking_enabled,
        tracking_paused=state.tracking_paused,
        tracking_label=state.label,
        tracking_status=state.status.value,
        last_successful_snapshot_at=state.last_successful_snapshot_at,
        last_snapshot_attempt_at=state.last_snapshot_attempt_at,
        last_snapshot_error=state.last_snapshot_error,
        snapshot_count=state.snapshot_count,
        history_start_at=state.history_start_at,
        next_snapshot_at=state.next_snapshot_at,
    )


async def _status_response(
    session: AsyncSession, repo: Repository
) -> TrackingStatusOut:
    return _tracking_out(repo, await tracking_state(session, repo))


@router.get(
    "",
    response_model=Paginated[RepoOut],
    summary="List tracked or known repositories",
)
async def list_repos(
    language: str | None = Query(None, description="Filter by language, e.g. python"),
    q: str | None = Query(
        None, min_length=1, max_length=100, description="Search in repo names"
    ),
    sort: str = Query("stars", pattern="^(stars|name|updated)$"),
    tracking: TrackingFilter = Query("tracked", description="Tracking scope"),
    tracking_status: TrackingStatusFilter | None = Query(
        default=None,
        alias="status",
        description="Derived collection health",
    ),
    label: str | None = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[RepoOut]:
    if tracking_status is None:
        repos, total = await list_repositories(
            session,
            language=language,
            search=q,
            sort=sort,
            limit=limit,
            offset=offset,
            tracking=tracking,
            label=label,
        )
    else:
        scope = (
            "all"
            if tracking_status == "untracked" and tracking == "tracked"
            else tracking
        )
        all_repos, _ = await list_repositories(
            session,
            language=language,
            search=q,
            sort=sort,
            limit=10000,
            offset=0,
            tracking=scope,
            label=label,
        )
        states = {repo.id: await tracking_state(session, repo) for repo in all_repos}
        filtered = [
            repo
            for repo in all_repos
            if states[repo.id].status.value == tracking_status
        ]
        total = len(filtered)
        repos = filtered[offset : offset + limit]

    items = [await _to_out(session, repo) for repo in repos]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return Paginated[RepoOut](
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=items,
    )


@router.post(
    "/{owner}/{name}/track",
    response_model=TrackingStatusOut,
    status_code=status.HTTP_200_OK,
    summary="Start tracking a repository",
    dependencies=[Depends(require_admin_api_key)],
)
async def track_repo(
    owner: str,
    name: str,
    payload: TrackingTrackIn | None = None,
    session: AsyncSession = Depends(get_session),
) -> TrackingStatusOut:
    full_name = f"{owner}/{name}"
    repo = await get_repository_by_name(session, full_name)
    if repo is None:
        try:
            async with GitHubClient() as client:
                fresh = await client.get_repo(full_name)
        except NotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"repository {full_name} not found on GitHub",
            ) from exc
        except GitHubError as exc:
            raise HTTPException(
                status_code=502, detail="GitHub repository lookup failed"
            ) from exc
        repo = await upsert_repository(session, fresh, track=False)
    label = None
    if payload is not None:
        label = payload.label if payload.label is not None else payload.tracking_label
    await track(session, repo, label=label)
    await session.commit()
    return await _status_response(session, repo)


@router.delete(
    "/{owner}/{name}/track",
    response_model=TrackingStatusOut,
    summary="Stop tracking without deleting history",
    dependencies=[Depends(require_admin_api_key)],
)
async def untrack_repo(
    owner: str,
    name: str,
    session: AsyncSession = Depends(get_session),
) -> TrackingStatusOut:
    repo = await _load_known_repo(session, owner, name)
    await untrack(session, repo)
    await session.commit()
    return await _status_response(session, repo)


@router.patch(
    "/{owner}/{name}/tracking",
    response_model=TrackingStatusOut,
    summary="Update tracking state and label",
    dependencies=[Depends(require_admin_api_key)],
)
async def patch_tracking(
    owner: str,
    name: str,
    payload: TrackingUpdate,
    session: AsyncSession = Depends(get_session),
) -> TrackingStatusOut:
    repo = await _load_known_repo(session, owner, name)
    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(status_code=422, detail="tracking update is empty")
    enabled = payload.enabled if "enabled" in fields else payload.tracking_enabled
    paused = payload.paused if "paused" in fields else payload.tracking_paused
    label = payload.label if "label" in fields else payload.tracking_label
    if enabled is not None:
        if enabled:
            await track(session, repo)
        else:
            await untrack(session, repo)
    if paused is not None:
        if paused:
            await pause(session, repo)
        else:
            await resume(session, repo)
    if "label" in fields or "tracking_label" in fields:
        await set_label(session, repo, label)
    await session.commit()
    return await _status_response(session, repo)


@router.get(
    "/{owner}/{name}/status",
    response_model=TrackingStatusOut,
    summary="Get snapshot collection health",
)
async def get_tracking_status(
    owner: str,
    name: str,
    session: AsyncSession = Depends(get_session),
) -> TrackingStatusOut:
    repo = await _load_known_repo(session, owner, name)
    return await _status_response(session, repo)


@router.post(
    "/{owner}/{name}/refresh",
    response_model=TrackingStatusOut,
    summary="Collect a repository snapshot now",
    dependencies=[Depends(require_admin_api_key)],
)
async def refresh_repo(
    owner: str,
    name: str,
    session: AsyncSession = Depends(get_session),
) -> TrackingStatusOut:
    repo = await _load_known_repo(session, owner, name)
    from collector.pipeline import run_snapshot

    await run_snapshot(repo_name=repo.full_name, force=True)
    session.expire_all()
    repo = await _load_known_repo(session, owner, name)
    return await _status_response(session, repo)


async def _load_known_repo(session: AsyncSession, owner: str, name: str) -> Repository:
    full_name = f"{owner}/{name}"
    repo = await get_repository_by_name(session, full_name)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"repository {full_name} not found")
    return repo


@router.get("/{owner}/{name}", response_model=RepoDetailOut, summary="Get a repository")
async def get_repo(
    repo: Repository = Depends(get_repo_or_404),
    session: AsyncSession = Depends(get_session),
) -> RepoDetailOut:
    latest_snapshot = await get_latest_snapshot(session, repo.id)
    velocities, _trend, _stars = await service.repo_velocity(
        session,
        repo.id,
        windows=(7, 30, 90),
        history_days=settings.analytics_history_days,
    )
    _events, active_burst = await service.repo_bursts(
        session,
        repo.id,
        history_days=settings.analytics_history_days,
        rolling_window=settings.analytics_rolling_window,
        z_threshold=settings.analytics_burst_z,
        min_delta=settings.analytics_burst_min_delta,
        min_duration=settings.analytics_burst_min_days,
    )
    state = await tracking_state(session, repo)
    return RepoDetailOut(
        id=repo.id,
        full_name=repo.full_name,
        description=repo.description,
        html_url=repo.html_url,
        language=repo.language,
        created_at=as_utc(repo.created_at),
        updated_at=as_utc(repo.updated_at),
        latest_snapshot=latest_snapshot,
        velocities=[
            VelocityOut.model_validate(v, from_attributes=True) for v in velocities
        ],
        active_burst=active_burst,
        tracking=_tracking_out(repo, state),
        tracking_enabled=state.tracking_enabled,
        tracking_paused=state.tracking_paused,
        tracking_label=state.label,
        tracking_status=state.status.value,
    )
