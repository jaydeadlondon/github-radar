from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary


async def save_repos(session: AsyncSession, repos: list[RepoSummary]) -> int:
    for repo in repos:
        stored = await upsert_repository(session, repo)
        await create_snapshot(
            session,
            stored.id,
            stargazers=repo.stargazers_count,
            forks=repo.forks_count,
        )
    await session.commit()
    return len(repos)
