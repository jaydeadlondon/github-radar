from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Repository, RepoSnapshot
from github.models import RepoSummary


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def upsert_repository(session: AsyncSession, repo: RepoSummary) -> Repository:
    existing = await session.scalar(
        select(Repository).where(Repository.full_name == repo.full_name)
    )
    if existing is None:
        existing = Repository(
            full_name=repo.full_name,
            description=repo.description,
            html_url=repo.html_url,
            language=repo.language,
            github_created_at=_parse_dt(repo.created_at),
            github_pushed_at=_parse_dt(repo.pushed_at),
        )
        session.add(existing)
    else:
        existing.description = repo.description
        existing.html_url = repo.html_url
        existing.language = repo.language
        existing.github_pushed_at = _parse_dt(repo.pushed_at)
    await session.flush()
    return existing


async def create_snapshot(
    session: AsyncSession,
    repo_id: int,
    *,
    stargazers: int,
    forks: int,
    open_issues: int = 0,
    observed_at: datetime | None = None,
) -> RepoSnapshot:
    snapshot = RepoSnapshot(
        repo_id=repo_id,
        stargazers_count=stargazers,
        forks_count=forks,
        open_issues_count=open_issues,
        observed_at=observed_at,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def get_latest_snapshot(
    session: AsyncSession, repo_id: int
) -> RepoSnapshot | None:
    return await session.scalar(
        select(RepoSnapshot)
        .where(RepoSnapshot.repo_id == repo_id)
        .order_by(RepoSnapshot.observed_at.desc())
        .limit(1)
    )


async def get_history(
    session: AsyncSession,
    repo_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> list[RepoSnapshot]:
    stmt = (
        select(RepoSnapshot)
        .where(RepoSnapshot.repo_id == repo_id)
        .order_by(RepoSnapshot.observed_at)
    )
    if since is not None:
        stmt = stmt.where(RepoSnapshot.observed_at >= since)
    if until is not None:
        stmt = stmt.where(RepoSnapshot.observed_at <= until)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(await session.scalars(stmt))


async def get_repository_by_name(
    session: AsyncSession, full_name: str
) -> Repository | None:
    return await session.scalar(
        select(Repository).where(Repository.full_name == full_name)
    )
