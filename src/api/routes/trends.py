from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_session
from api.schemas import RepoOut
from db.repositories import top_growth

router = APIRouter(prefix="/trends", tags=["trends"])

ALLOWED_WINDOWS = (7, 30, 90)


@router.get("", response_model=list[RepoOut], summary="Top repositories by star growth")
async def trends(
    window: int = Query(7, ge=7, le=90, description="Time window in days"),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> list[RepoOut]:
    if window not in ALLOWED_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid window: {window}. Allowed values: {ALLOWED_WINDOWS}.",
        )
    since = datetime.now(UTC) - timedelta(days=window)
    ranked = await top_growth(session, since, limit=limit)
    return [
        RepoOut(
            id=repo.id,
            full_name=repo.full_name,
            description=repo.description,
            html_url=repo.html_url,
            language=repo.language,
            stargazers_count=repo.latest_stargazers,
            forks_count=repo.latest_forks,
        )
        for repo, _growth in ranked
    ]
