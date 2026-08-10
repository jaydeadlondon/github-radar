from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Repository
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
