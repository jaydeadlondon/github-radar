from sqlalchemy import select

import collector.jobs as jobs
from collector.pipeline import SnapshotRunResult
from db.models import JobLock, SnapshotJob


async def test_execute_snapshot_job_persists_success_and_releases_global_lock(
    db_session,
    monkeypatch,
):
    async def fake_snapshot_result(**_kwargs):
        return SnapshotRunResult(
            total_repositories=3,
            succeeded_repositories=2,
            failed_repositories=1,
            skipped_repositories=0,
        )

    monkeypatch.setattr(jobs, "run_snapshot_result", fake_snapshot_result)

    job_id = await jobs.execute_snapshot_job()

    stored = await db_session.scalar(
        select(SnapshotJob).where(SnapshotJob.id == job_id)
    )
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.total_repositories == 3
    assert stored.succeeded_repositories == 2
    assert stored.failed_repositories == 1
    assert (
        await db_session.scalar(
            select(JobLock).where(JobLock.name == "snapshot:global")
        )
        is None
    )
