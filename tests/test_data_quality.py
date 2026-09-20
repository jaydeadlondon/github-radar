from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from db.models import RepoSnapshot
from db.repositories import (
    create_snapshot,
    get_history,
    get_latest_snapshot,
    upsert_repository,
)
from github.models import RepoSummary


def _summary() -> RepoSummary:
    return RepoSummary(
        id=1,
        full_name="acme/quality",
        html_url="https://github.com/acme/quality",
        stargazers_count=100,
        forks_count=1,
    )


async def test_decrease_is_retained_but_excluded_from_analytics(db_session):
    repo = await upsert_repository(db_session, _summary())
    first = datetime(2026, 1, 1, tzinfo=UTC)
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=1, observed_at=first
    )
    rejected = await create_snapshot(
        db_session,
        repo.id,
        stargazers=90,
        forks=1,
        observed_at=first + timedelta(days=1),
    )
    await db_session.commit()

    assert rejected.quality_status == "rejected"
    assert rejected.quality_reason == "stars_decreased"
    assert len(await get_history(db_session, repo.id)) == 1
    assert (await get_latest_snapshot(db_session, repo.id)).stargazers_count == 100
    assert await db_session.scalar(select(func.count(RepoSnapshot.id))) == 2


async def test_same_timestamp_is_idempotent_and_utc_normalized(db_session):
    repo = await upsert_repository(db_session, _summary())
    moment = datetime(2026, 2, 1, 10, tzinfo=UTC)
    first = await create_snapshot(
        db_session, repo.id, stargazers=100, forks=1, observed_at=moment
    )
    duplicate = await create_snapshot(
        db_session,
        repo.id,
        stargazers=101,
        forks=2,
        observed_at=moment.astimezone(UTC),
    )
    await db_session.commit()

    assert duplicate.id == first.id
    assert duplicate.stargazers_count == 100
    assert duplicate.observed_at.replace(tzinfo=UTC).tzinfo is UTC
    assert await db_session.scalar(select(func.count(RepoSnapshot.id))) == 1


async def test_quality_history_endpoint_exposes_rejected_observations(
    api_client, db_session
):
    repo = await upsert_repository(db_session, _summary())
    first = datetime(2026, 4, 1, tzinfo=UTC)
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=1, observed_at=first
    )
    await create_snapshot(
        db_session,
        repo.id,
        stargazers=90,
        forks=1,
        observed_at=first + timedelta(days=1),
    )
    await db_session.commit()

    response = await api_client.get("/api/v1/repos/acme/quality/history/quality")
    assert response.status_code == 200
    assert [item["quality_status"] for item in response.json()] == [
        "accepted",
        "rejected",
    ]
    assert response.json()[-1]["quality_reason"] == "stars_decreased"


async def test_explicit_decrease_is_marked_anomalous(db_session):
    repo = await upsert_repository(db_session, _summary())
    first = datetime(2026, 3, 1, tzinfo=UTC)
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=1, observed_at=first
    )
    corrected = await create_snapshot(
        db_session,
        repo.id,
        stargazers=90,
        forks=1,
        observed_at=first + timedelta(days=1),
        allow_decrease=True,
    )
    assert corrected.quality_status == "anomalous"
    assert corrected.quality_reason == "stars_decreased_explicit"
