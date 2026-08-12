from datetime import UTC, datetime, timedelta
from sqlalchemy import func, select
from db.models import Repository, RepoSnapshot
from db.repositories import (
    create_snapshot,
    get_history,
    get_latest_snapshot,
    get_repository_by_name,
    upsert_repository,
)
from github.models import RepoSummary

NOW = datetime.now(UTC)
DAY = timedelta(days=1)


def _repo_summary(full_name: str = "psf/requests", stars: int = 100) -> RepoSummary:
    return RepoSummary(
        id=1,
        full_name=full_name,
        description="An HTTP library",
        html_url=f"https://github.com/{full_name}",
        language="Python",
        stargazers_count=stars,
        forks_count=10,
        created_at="2011-02-13T18:44:23Z",
        pushed_at="2024-01-01T00:00:00Z",
    )


async def test_upsert_creates_then_updates(db_session):
    repo = await upsert_repository(db_session, _repo_summary())
    assert repo.id is not None
    assert repo.full_name == "psf/requests"
    assert repo.github_created_at is not None
    assert repo.language == "Python"

    updated = await upsert_repository(
        db_session, _repo_summary(full_name="psf/requests", stars=500)
    )
    assert updated.id == repo.id
    count = (
        await db_session.execute(select(func.count()).select_from(Repository))
    ).scalar_one()
    assert count == 1


async def test_create_and_latest_snapshot(db_session):
    repo = await upsert_repository(db_session, _repo_summary())
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=10, observed_at=NOW
    )
    await create_snapshot(
        db_session, repo.id, stargazers=150, forks=12, observed_at=NOW + DAY
    )

    latest = await get_latest_snapshot(db_session, repo.id)
    assert latest is not None
    assert latest.stargazers_count == 150
    assert latest.forks_count == 12


async def test_history_time_range(db_session):
    repo = await upsert_repository(db_session, _repo_summary())
    await create_snapshot(
        db_session, repo.id, stargazers=1, forks=0, observed_at=NOW - DAY * 5
    )
    await create_snapshot(
        db_session, repo.id, stargazers=2, forks=0, observed_at=NOW - DAY * 3
    )
    await create_snapshot(db_session, repo.id, stargazers=3, forks=0, observed_at=NOW)

    history = await get_history(db_session, repo.id, since=NOW - DAY * 4)
    assert [s.stargazers_count for s in history] == [2, 3]

    full = await get_history(db_session, repo.id)
    assert len(full) == 3
    assert full[0].observed_at <= full[1].observed_at <= full[2].observed_at


async def test_get_repository_by_name(db_session):
    await upsert_repository(db_session, _repo_summary())
    found = await get_repository_by_name(db_session, "psf/requests")
    assert found is not None
    assert await get_repository_by_name(db_session, "no/such") is None


async def test_snapshots_are_deleted_with_repository(db_session):
    repo = await upsert_repository(db_session, _repo_summary())
    await create_snapshot(db_session, repo.id, stargazers=1, forks=0, observed_at=NOW)

    await db_session.delete(repo)
    await db_session.commit()

    remaining = (
        await db_session.execute(select(func.count()).select_from(RepoSnapshot))
    ).scalar_one()
    assert remaining == 0
