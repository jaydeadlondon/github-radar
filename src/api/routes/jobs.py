from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_session, require_read_api_key
from api.schemas import JobStatusValue, Paginated, SnapshotJobOut
from db.jobs import get_snapshot_job, list_snapshot_jobs

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_read_api_key)],
)


def _job_out(job) -> SnapshotJobOut:
    return SnapshotJobOut(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        started_at=job.started_at,
        finished_at=job.finished_at,
        total_repositories=job.total_repositories,
        succeeded_repositories=job.succeeded_repositories,
        failed_repositories=job.failed_repositories,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("", response_model=Paginated[SnapshotJobOut])
async def get_jobs(
    status: JobStatusValue | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[SnapshotJobOut]:
    jobs, total = await list_snapshot_jobs(
        session,
        status=status,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(jobs) if offset + len(jobs) < total else None
    return Paginated(
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=[_job_out(job) for job in jobs],
    )


@router.get("/{job_id}", response_model=SnapshotJobOut)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> SnapshotJobOut:
    job = await get_snapshot_job(session, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"snapshot job {job_id} not found")
    return _job_out(job)
