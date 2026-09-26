from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_repo_or_404, get_session, require_read_api_key
from api.schemas import SnapshotOut, SnapshotQualityOut
from db.models import Repository
from db.repositories import get_history

router = APIRouter(
    prefix="/repos",
    tags=["repos"],
    dependencies=[Depends(require_read_api_key)],
)


@router.get(
    "/{owner}/{name}/history/quality",
    response_model=list[SnapshotQualityOut],
    summary="Get snapshot history including quality decisions",
)
async def repo_history_quality(
    repo: Repository = Depends(get_repo_or_404),
    since: datetime | None = Query(None, description="Start of the time window"),
    until: datetime | None = Query(None, description="End of the time window"),
    limit: int | None = Query(None, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[SnapshotQualityOut]:
    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=422, detail="`since` must not be later than `until`."
        )
    snapshots = await get_history(
        session,
        repo.id,
        since=since,
        until=until,
        limit=limit,
        include_rejected=True,
    )
    return [SnapshotQualityOut.model_validate(snapshot) for snapshot in snapshots]


@router.get(
    "/{owner}/{name}/history",
    response_model=list[SnapshotOut],
    summary="Get snapshot history for a repository",
)
async def repo_history(
    repo: Repository = Depends(get_repo_or_404),
    since: datetime | None = Query(None, description="Start of the time window"),
    until: datetime | None = Query(None, description="End of the time window"),
    limit: int | None = Query(
        None, ge=1, le=1000, description="Maximum number of snapshots"
    ),
    session: AsyncSession = Depends(get_session),
) -> list[SnapshotOut]:
    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=422, detail="`since` must not be later than `until`."
        )
    snapshots = await get_history(
        session, repo.id, since=since, until=until, limit=limit
    )
    return [SnapshotOut.model_validate(s) for s in snapshots]
