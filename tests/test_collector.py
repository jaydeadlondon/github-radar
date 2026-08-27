from sqlalchemy import func, select

import collector.pipeline as pipeline
import collector.store as store
from db.models import Repository, RepoSnapshot
from db.repositories import upsert_repository
from github.models import RepoSummary


def _repo(full_name: str, stars: int) -> RepoSummary:
    return RepoSummary(
        id=hash(full_name),
        full_name=full_name,
        description="Some description",
        html_url=f"https://github.com/{full_name}",
        language="Python",
        stargazers_count=stars,
        forks_count=1,
        created_at="2020-01-01T00:00:00Z",
        pushed_at="2024-01-01T00:00:00Z",
    )


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_save_repos_stores_repos_and_initial_snapshots(db_session):
    repos = [_repo("psf/requests", 100), _repo("pallets/flask", 200)]

    saved = await store.save_repos(db_session, repos)

    assert saved == 2
    assert await _count(db_session, Repository) == 2
    assert await _count(db_session, RepoSnapshot) == 2


async def test_save_repos_is_idempotent(db_session):
    repos = [_repo("psf/requests", 100)]

    await store.save_repos(db_session, repos)
    await store.save_repos(db_session, repos)

    assert await _count(db_session, Repository) == 1


class FakeGitHubClient:
    def __init__(self, summaries: list[RepoSummary]) -> None:
        self._by_name = {repo.full_name: repo for repo in summaries}

    async def __aenter__(self) -> "FakeGitHubClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_repo(self, full_name: str) -> RepoSummary:
        return self._by_name[full_name]


async def test_run_snapshot_records_current_state(db_session, monkeypatch):
    await upsert_repository(db_session, _repo("psf/requests", 100))
    await db_session.commit()

    fake = FakeGitHubClient([_repo("psf/requests", 250)])
    monkeypatch.setattr(pipeline, "GitHubClient", lambda **kwargs: fake)

    saved = await pipeline.run_snapshot()

    assert saved == 1
    assert await _count(db_session, RepoSnapshot) == 1
    latest = (
        await db_session.execute(
            select(RepoSnapshot).order_by(RepoSnapshot.id.desc()).limit(1)
        )
    ).scalar_one()
    assert latest.stargazers_count == 250


async def test_run_snapshot_empty_db(db_session, monkeypatch):
    fake = FakeGitHubClient([])
    monkeypatch.setattr(pipeline, "GitHubClient", lambda **kwargs: fake)

    saved = await pipeline.run_snapshot()

    assert saved == 0
    assert await _count(db_session, RepoSnapshot) == 0
