import logging

from sqlalchemy import select

from alerts.runner import run_alert_evaluation
from db.base import SessionFactory
from db.models import Repository
from db.repositories import create_snapshot
from github.client import GitHubClient
from github.errors import GitHubError

logger = logging.getLogger(__name__)


async def run_snapshot() -> int:
    async with SessionFactory() as session:
        repositories = list(
            (await session.scalars(select(Repository).order_by(Repository.id))).all()
        )

    saved = 0
    updated_repo_ids: list[int] = []
    async with GitHubClient() as client:
        async with SessionFactory() as session:
            for repo in repositories:
                try:
                    fresh = await client.get_repo(repo.full_name)
                except GitHubError:
                    logger.warning("skipping %s: fetch failed", repo.full_name)
                    continue
                await create_snapshot(
                    session,
                    repo.id,
                    stargazers=fresh.stargazers_count,
                    forks=fresh.forks_count,
                )
                saved += 1
                updated_repo_ids.append(repo.id)
            await session.commit()

    if updated_repo_ids:
        try:
            await run_alert_evaluation(updated_repo_ids)
        except Exception:
            logger.exception("alert evaluation failed after snapshot collection")
    return saved
