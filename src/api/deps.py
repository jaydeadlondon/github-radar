import hmac
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Path, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.base import SessionFactory
from db.models import Repository
from db.repositories import get_repository_by_name

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _matches(provided: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(provided, expected)


async def require_read_api_key(
    api_key: str | None = Security(api_key_header),
) -> str | None:
    """Require a read key when API authentication is enabled."""

    if not settings.api_auth_enabled:
        return None
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if _matches(api_key, settings.admin_api_key):
        return "admin"
    if _matches(api_key, settings.api_key):
        return "read"
    raise HTTPException(status_code=403, detail="API key is not valid")


async def require_admin_api_key(
    api_key: str | None = Security(api_key_header),
) -> str | None:
    """Require the admin key for mutations when API authentication is enabled."""

    if not settings.api_auth_enabled:
        return None
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Admin API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if not _matches(api_key, settings.admin_api_key):
        raise HTTPException(status_code=403, detail="Admin API key required")
    return "admin"


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
