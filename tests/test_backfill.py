from __future__ import annotations

from sqlalchemy import func, select

from collector.backfill import run_backfill
from db.models import RepoSnapshot
from db.repositories import upsert_repository
from github.models import RepoSummary


class _BackfillClient:
    def __init__(self):
        self.summary = RepoSummary(
            id=1,
            full_name="acme/backfill",
            html_url="https://github.com/acme/backfill",
            stargazers_count=103,
            forks_count=2,
        )

    async def get_repo(self, _name):
        return self.summary

    async def get_stargazer_dates(self, _name, *, max_pages=None):
        return [
            "2026-01-02T12:00:00Z",
            "2026-01-03T12:00:00Z",
            "2026-01-04T12:00:00Z",
        ]

    async def close(self):
        return None


async def test_backfill_dry_run_is_resumable_and_does_not_write(db_session):
    repo = await upsert_repository(
        db_session,
        RepoSummary(
            id=1,
            full_name="acme/backfill",
            html_url="https://github.com/acme/backfill",
            stargazers_count=103,
            forks_count=2,
        ),
    )
    await db_session.commit()
    result = await run_backfill(
        [repo.full_name],
        days=3,
        dry_run=True,
        client=_BackfillClient(),
        session=db_session,
    )
    assert result.planned == 3
    assert result.inserted == 0
    assert await db_session.scalar(select(func.count(RepoSnapshot.id))) == 0

    result = await run_backfill(
        [repo.full_name],
        days=3,
        client=_BackfillClient(),
        session=db_session,
    )
    first_count = await db_session.scalar(select(func.count(RepoSnapshot.id)))
    assert result.inserted == first_count
    assert first_count <= 3
