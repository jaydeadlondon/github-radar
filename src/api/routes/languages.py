from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_session
from db.models import Repository, RepoSnapshot

router = APIRouter(prefix="/languages", tags=["languages"])


class LanguageOut(BaseModel):
    language: str
    repository_count: int
    total_stars: int


@router.get("", response_model=list[LanguageOut], summary="Language aggregates")
async def languages(
    session: AsyncSession = Depends(get_session),
) -> list[LanguageOut]:
    latest = (
        select(
            RepoSnapshot.repo_id,
            func.max(RepoSnapshot.observed_at).label("latest_at"),
        )
        .group_by(RepoSnapshot.repo_id)
        .subquery()
    )
    rows = await session.execute(
        select(
            Repository.language,
            func.count().label("repo_count"),
            func.sum(RepoSnapshot.stargazers_count).label("total_stars"),
        )
        .join(latest, latest.c.repo_id == Repository.id)
        .join(
            RepoSnapshot,
            and_(
                RepoSnapshot.repo_id == latest.c.repo_id,
                RepoSnapshot.observed_at == latest.c.latest_at,
            ),
        )
        .group_by(Repository.language)
        .order_by(func.sum(RepoSnapshot.stargazers_count).desc())
    )
    return [
        LanguageOut(
            language=language or "other",
            repository_count=repo_count,
            total_stars=int(total_stars or 0),
        )
        for language, repo_count, total_stars in rows
    ]
