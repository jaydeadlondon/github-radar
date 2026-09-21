from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_session
from api.routes.operations import check_readiness
from api.schemas import ReadyOut
from config import settings
from db.models import Repository
from observability import metrics

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthOut, summary="Service health check")
async def health(session: AsyncSession = Depends(get_session)) -> HealthOut:
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    metrics.set_gauge("radar_database_up", 1 if database == "ok" else 0)
    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        database=database,
    )


@router.get("/ready", response_model=ReadyOut, summary="Readiness check")
async def ready(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> ReadyOut:
    is_ready, database, migrations, detail = await check_readiness(session)
    if not is_ready:
        response.status_code = 503
    return ReadyOut(
        status="ready" if is_ready else "not_ready",
        database=database,
        migrations=migrations,
        detail=detail,
    )


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=True)
async def metrics_endpoint(
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    try:
        repositories = list((await session.scalars(select(Repository))).all())
        now = datetime.now(UTC)
        stale_after = timedelta(hours=settings.tracking_stale_after_hours or 48)
        tracked = [repo for repo in repositories if repo.tracking_enabled]
        stale = []
        for repo in tracked:
            last_success = repo.last_successful_snapshot_at
            if last_success is not None and last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=UTC)
            if (
                not repo.tracking_paused
                and (last_success is None or last_success < now - stale_after)
            ):
                stale.append(repo)
        metrics.set_gauge("radar_tracked_repositories", len(tracked))
        metrics.set_gauge("radar_stale_repositories", len(stale))
    except Exception:
        metrics.set_gauge("radar_tracked_repositories", 0)
        metrics.set_gauge("radar_stale_repositories", 0)
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")
