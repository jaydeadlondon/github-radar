from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_admin_api_key, require_read_api_key
from api.schemas import ConfigDiagnosticsOut, RateLimitOut
from config import configuration_warnings, settings
from db.base import engine
from github.client import GitHubClient
from github.errors import GitHubError

router = APIRouter(
    prefix="/ops",
    tags=["operations"],
    dependencies=[Depends(require_read_api_key)],
)


@router.get("/github/rate-limit", response_model=RateLimitOut)
async def github_rate_limit() -> RateLimitOut:
    try:
        async with GitHubClient() as client:
            quota = await client.get_rate_limit()
    except GitHubError as exc:
        raise HTTPException(
            status_code=502, detail="GitHub rate limit lookup failed"
        ) from exc
    reset = int(quota["reset"])
    return RateLimitOut(
        resource=str(quota["resource"]),
        limit=int(quota["limit"]),
        remaining=int(quota["remaining"]),
        used=int(quota["used"]),
        reset_at=datetime.fromtimestamp(reset, UTC) if reset else None,
        warning=(
            "GitHub API quota is nearly exhausted"
            if int(quota["remaining"]) <= settings.github_rate_limit_warning_remaining
            else None
        ),
    )


@router.get(
    "/config",
    response_model=ConfigDiagnosticsOut,
    dependencies=[Depends(require_admin_api_key)],
)
async def config_diagnostics() -> ConfigDiagnosticsOut:
    return ConfigDiagnosticsOut(
        environment=settings.environment,
        api_auth_enabled=settings.api_auth_enabled,
        admin_key_configured=bool(settings.admin_api_key),
        read_key_configured=bool(settings.api_key),
        database_backend=engine.url.get_backend_name(),
        scheduler_enabled=settings.scheduler_enabled,
        webhook_provider=settings.webhook_provider,
        insecure_warnings=configuration_warnings(),
    )


async def check_readiness(session: AsyncSession) -> tuple[bool, str, str, str | None]:
    try:
        await session.execute(text("SELECT 1 FROM repositories LIMIT 1"))
        await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception as exc:
        return False, "unavailable", "unknown", str(exc)
    return True, "ok", "ok", None
