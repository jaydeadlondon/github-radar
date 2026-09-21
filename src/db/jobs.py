from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import JobLock, SnapshotJob


def utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def try_acquire_lock(
    session: AsyncSession,
    name: str,
    owner_id: str,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> bool:
    moment = _as_utc(now or utc_now())
    expires = moment + timedelta(seconds=max(ttl_seconds, 1))
    lock = await session.get(JobLock, name)
    if (
        lock is not None
        and _as_utc(lock.expires_at) > moment
        and lock.owner_id != owner_id
    ):
        return False

    if lock is None:
        session.add(
            JobLock(
                name=name,
                owner_id=owner_id,
                acquired_at=moment,
                expires_at=expires,
            )
        )
    else:
        lock.owner_id = owner_id
        lock.acquired_at = moment
        lock.expires_at = expires

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def renew_lock(
    session: AsyncSession,
    name: str,
    owner_id: str,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> bool:
    moment = _as_utc(now or utc_now())
    result = await session.execute(
        update(JobLock)
        .where(JobLock.name == name, JobLock.owner_id == owner_id)
        .values(
            acquired_at=moment,
            expires_at=moment + timedelta(seconds=max(ttl_seconds, 1)),
        )
    )
    await session.commit()
    return bool(result.rowcount)


async def release_lock(
    session: AsyncSession,
    name: str,
    owner_id: str,
) -> None:
    await session.execute(
        delete(JobLock).where(JobLock.name == name, JobLock.owner_id == owner_id)
    )
    await session.commit()


async def create_snapshot_job(
    session: AsyncSession,
    job_id: str,
    *,
    job_type: str = "snapshot",
    started_at: datetime | None = None,
) -> SnapshotJob:
    job = SnapshotJob(
        id=job_id,
        job_type=job_type,
        status="running",
        started_at=started_at or utc_now(),
    )
    session.add(job)
    await session.commit()
    return job


async def get_snapshot_job(
    session: AsyncSession,
    job_id: str,
) -> SnapshotJob | None:
    return await session.get(SnapshotJob, job_id)


async def list_snapshot_jobs(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SnapshotJob], int]:
    filters = []
    if status is not None:
        filters.append(SnapshotJob.status == status)
    total = int(
        await session.scalar(select(func.count(SnapshotJob.id)).where(*filters)) or 0
    )
    rows = await session.scalars(
        select(SnapshotJob)
        .where(*filters)
        .order_by(SnapshotJob.started_at.desc(), SnapshotJob.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), total


async def finish_snapshot_job(
    session: AsyncSession,
    job_id: str,
    *,
    status: str,
    finished_at: datetime | None = None,
    total_repositories: int | None = None,
    succeeded_repositories: int | None = None,
    failed_repositories: int | None = None,
    error: str | None = None,
) -> SnapshotJob | None:
    values: dict[str, object] = {
        "status": status,
        "finished_at": finished_at or utc_now(),
        "error": error,
    }
    if total_repositories is not None:
        values["total_repositories"] = total_repositories
    if succeeded_repositories is not None:
        values["succeeded_repositories"] = succeeded_repositories
    if failed_repositories is not None:
        values["failed_repositories"] = failed_repositories
    await session.execute(
        update(SnapshotJob).where(SnapshotJob.id == job_id).values(**values)
    )
    await session.commit()
    return await session.get(SnapshotJob, job_id)
