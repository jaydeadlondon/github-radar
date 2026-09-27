from datetime import UTC, datetime

from db.jobs import create_snapshot_job, finish_snapshot_job


async def test_snapshot_job_api_lists_and_returns_job(api_client, db_session):
    await create_snapshot_job(
        db_session,
        "job-api-1",
        started_at=datetime(2026, 9, 20, 12, tzinfo=UTC),
    )
    await finish_snapshot_job(
        db_session,
        "job-api-1",
        status="succeeded",
        total_repositories=1,
        succeeded_repositories=1,
    )

    listed = await api_client.get("/api/v1/jobs?status=succeeded")
    detail = await api_client.get("/api/v1/jobs/job-api-1")

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["status"] == "succeeded"
