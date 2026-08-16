from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_repo_or_404, get_session
from api.schemas import Paginated, RepoDetailOut, RepoOut
from db.models import Repository
from db.repositories import get_latest_snapshot, list_repositories

router = APIRouter(prefix="/repos", tags=["repos"])


def _to_out(repo: Repository) -> RepoOut:
    return RepoOut(
        id=repo.id,
        full_name=repo.full_name,
        description=repo.description,
        html_url=repo.html_url,
        language=repo.language,
        stargazers_count=repo.latest_stargazers,
        forks_count=repo.latest_forks,
    )


@router.get(
    "",
    response_model=Paginated[RepoOut],
    summary="List tracked repositories",
)
async def list_repos(
    language: str | None = Query(None, description="Filter by language, e.g. python"),
    sort: str = Query("stars", pattern="^(stars|name|updated)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[RepoOut]:
    repos, total = await list_repositories(
        session, language=language, sort=sort, limit=limit, offset=offset
    )
    next_offset = offset + limit if offset + limit < total else None
    return Paginated[RepoOut](
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=[_to_out(repo) for repo in repos],
    )


@router.get("/{owner}/{name}", response_model=RepoDetailOut, summary="Get a repository")
async def get_repo(
    repo: Repository = Depends(get_repo_or_404),
    session: AsyncSession = Depends(get_session),
) -> RepoDetailOut:
    latest_snapshot = await get_latest_snapshot(session, repo.id)
    return RepoDetailOut(
        id=repo.id,
        full_name=repo.full_name,
        description=repo.description,
        html_url=repo.html_url,
        language=repo.language,
        created_at=repo.created_at,
        updated_at=repo.updated_at,
        latest_snapshot=latest_snapshot,
    )
