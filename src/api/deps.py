from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import SessionFactory
from db.models import Repository
from db.repositories import get_repository_by_name


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def get_repo_or_404(
    owner: str = Path(
        ..., min_length=1, max_length=100, description="Repository owner"
    ),
    name: str = Path(..., min_length=1, max_length=100, description="Repository name"),
    session: AsyncSession = Depends(get_session),
) -> Repository:
    full_name = f"{owner}/{name}"
    repo = await get_repository_by_name(session, full_name)
    if repo is None:
        raise HTTPException(
            status_code=404,
            detail=f"Repository not tracked: {full_name}. "
            "Run `radar repos add` or `radar top --save` to track it.",
        )
    return repo
