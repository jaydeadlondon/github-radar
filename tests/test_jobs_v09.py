from datetime import UTC, datetime, timedelta

from db.jobs import (
    create_snapshot_job,
    finish_snapshot_job,
    get_snapshot_job,
    list_snapshot_jobs,
    release_lock,
    try_acquire_lock,
)


async def test_job_lock_is_exclusive_and_expired_leases_can_be_reclaimed(db_session):
    moment = datetime(2026, 9, 20, 12, tzinfo=UTC)

    assert await try_acquire_lock(
        db_session,
        "snapshot",
        "worker-a",
        ttl_seconds=60,
        now=moment,
    )
    assert not await try_acquire_lock(
        db_session,
        "snapshot",
        "worker-b",
        ttl_seconds=60,
        now=moment + timedelta(seconds=1),
    )
    assert await try_acquire_lock(
        db_session,
        "snapshot",
        "worker-b",
        ttl_seconds=60,
        now=moment + timedelta(seconds=61),
    )

    await release_lock(db_session, "snapshot", "worker-b")
    assert await try_acquire_lock(
        db_session,
        "snapshot",
        "worker-a",
        ttl_seconds=60,
        now=moment + timedelta(seconds=62),
    )


async def test_snapshot_job_lifecycle_is_queryable(db_session):
    started = datetime(2026, 9, 20, 12, tzinfo=UTC)
    job = await create_snapshot_job(db_session, "job-1", started_at=started)

    assert job.status == "running"
    stored = await get_snapshot_job(db_session, "job-1")
    assert stored is not None

    await finish_snapshot_job(
        db_session,
        "job-1",
        status="succeeded",
        finished_at=started + timedelta(seconds=3),
        total_repositories=2,
        succeeded_repositories=2,
        failed_repositories=0,
    )
    stored = await get_snapshot_job(db_session, "job-1")
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.total_repositories == 2

    jobs, total = await list_snapshot_jobs(db_session, status="succeeded")
    assert total == 1
    assert [item.id for item in jobs] == ["job-1"]
