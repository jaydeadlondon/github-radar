# Commit 13 — feat: expose alert rule CRUD API

Reference implementation commit: `6609d5edfc62399ab9645ff7d41c34fa0ea3c9a0`
Apply after: `Commit 12`

## Goal

Expose paginated alert-rule CRUD endpoints with domain validation and repository lookup.

## Files

### `src/api/app.py`

Replace this file with the complete post-commit content below.

````python
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes import alerts, analytics, health, history, languages, repos, trends
from api.schemas import ErrorOut
from config import settings
from db.base import engine
from version import __version__

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class DashboardStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return JSONResponse(
                    status_code=404,
                    content=ErrorOut(
                        detail=f"Not found: /{path}", code=404
                    ).model_dump(),
                )
            raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    if settings.scheduler_enabled:
        from collector.scheduler import build_scheduler, run_snapshot_job

        scheduler = build_scheduler(settings, run_snapshot_job)
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info(
            "background scheduler started (every %sh)",
            settings.scheduler_interval_hours,
        )

    yield

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)

    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="GitHub Radar",
        description="Analytics service for tracking rising stars on GitHub.",
        version=__version__,
        lifespan=lifespan,
    )
    app.middleware("http")(request_logging)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.include_router(history.router, prefix=settings.api_prefix)
    app.include_router(repos.router, prefix=settings.api_prefix)
    app.include_router(trends.router, prefix=settings.api_prefix)
    app.include_router(languages.router, prefix=settings.api_prefix)
    app.include_router(analytics.router, prefix=settings.api_prefix)
    app.include_router(alerts.router, prefix=settings.api_prefix)
    app.include_router(health.router)

    app.mount(
        "/", DashboardStaticFiles(directory=_WEB_DIR, html=True), name="dashboard"
    )
    return app


async def request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %s (%.1f ms) [%s]",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail
    if not isinstance(detail, str):
        detail = str(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorOut(detail=detail, code=exc.status_code).model_dump(),
    )


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorOut(detail="Internal server error", code=500).model_dump(),
    )
````

### `src/api/routes/alerts.py`

Create this file with the complete content below.

````python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from alerts import RuleSpec, validate_rule
from api.deps import get_session
from api.schemas import AlertRuleCreate, AlertRuleOut, AlertRuleUpdate, Paginated
from db.alerts import create_rule, delete_rule, get_rule, list_rules
from db.models import AlertRule
from db.repositories import get_repository_by_name

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _validated_spec(spec: RuleSpec) -> RuleSpec:
    try:
        return validate_rule(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _rule_out(rule: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=rule.id,
        repository=rule.repository.full_name,
        kind=rule.kind,
        threshold=rule.threshold,
        window_days=rule.window_days,
        enabled=rule.enabled,
        last_value=rule.last_value,
        last_evaluated_at=rule.last_evaluated_at,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


async def _rule_or_404(session: AsyncSession, rule_id: int) -> AlertRule:
    rule = await get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"alert rule {rule_id} not found")
    return rule


@router.get("/rules", response_model=Paginated[AlertRuleOut])
async def get_rules(
    repository: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[AlertRuleOut]:
    repo_id = None
    if repository:
        repo = await get_repository_by_name(session, repository)
        if repo is None:
            return Paginated(total=0, offset=offset, limit=limit, next_offset=None, items=[])
        repo_id = repo.id
    rules, total = await list_rules(
        session,
        repo_id=repo_id,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(rules) if offset + len(rules) < total else None
    return Paginated(
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=[_rule_out(rule) for rule in rules],
    )


@router.post(
    "/rules",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_rule(
    payload: AlertRuleCreate,
    session: AsyncSession = Depends(get_session),
) -> AlertRuleOut:
    repo = await get_repository_by_name(session, payload.repository)
    if repo is None:
        raise HTTPException(
            status_code=404,
            detail=f"repository {payload.repository} not found",
        )
    spec = _validated_spec(
        RuleSpec(
            kind=payload.kind,
            threshold=payload.threshold,
            window_days=payload.window_days,
        )
    )
    rule = await create_rule(session, repo, spec, enabled=payload.enabled)
    await session.commit()
    return _rule_out(rule)


@router.get("/rules/{rule_id}", response_model=AlertRuleOut)
async def get_rule_by_id(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> AlertRuleOut:
    return _rule_out(await _rule_or_404(session, rule_id))


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
async def patch_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    session: AsyncSession = Depends(get_session),
) -> AlertRuleOut:
    rule = await _rule_or_404(session, rule_id)
    fields = payload.model_fields_set
    spec = _validated_spec(
        RuleSpec(
            kind=payload.kind if "kind" in fields and payload.kind else rule.kind,
            threshold=payload.threshold if "threshold" in fields else rule.threshold,
            window_days=payload.window_days if "window_days" in fields else rule.window_days,
        )
    )
    condition_changed = (
        rule.kind,
        rule.threshold,
        rule.window_days,
    ) != (spec.kind, spec.threshold, spec.window_days)
    rule.kind = spec.kind
    rule.threshold = spec.threshold
    rule.window_days = spec.window_days
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if condition_changed:
        rule.last_value = None
        rule.last_evaluated_at = None
    await session.flush()
    await session.refresh(rule, attribute_names=["updated_at"])
    await session.commit()
    return _rule_out(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    rule = await _rule_or_404(session, rule_id)
    await delete_rule(session, rule)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
````

### `src/api/schemas.py`

Replace this file with the complete post-commit content below.

````python
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    total: int
    offset: int
    limit: int
    next_offset: int | None
    items: list[T]


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stargazers_count: int
    forks_count: int
    open_issues_count: int
    observed_at: datetime


class RepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    stars_per_day: float | None = None


class TrendOut(RepoOut):
    stars_per_day: float


class VelocityOut(BaseModel):
    window_days: int
    stars_per_day: float
    stars_gained: int
    start_day: date
    end_day: date


class RepoDetailOut(BaseModel):
    id: int
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_snapshot: SnapshotOut | None = None
    velocities: list[VelocityOut] = []
    active_burst: bool = False


class ErrorOut(BaseModel):
    detail: str
    code: int


class SlopeOut(BaseModel):
    slope: float
    intercept: float
    r_squared: float
    n_points: int


class RepoBriefOut(BaseModel):
    owner: str
    name: str
    full_name: str
    stars: int


class RepoVelocityOut(BaseModel):
    repo: RepoBriefOut
    velocities: list[VelocityOut]
    trend: SlopeOut | None = None


class SeriesPointOut(BaseModel):
    day: date
    stars: int
    delta: int
    stars_avg: float | None = None
    delta_avg: float | None = None


class RepoSeriesOut(BaseModel):
    repo: RepoBriefOut
    smooth_window: int
    points: list[SeriesPointOut]


class CompareSeriesOut(BaseModel):
    full_name: str
    values: list[float | None]


class CompareOut(BaseModel):
    mode: str
    window_days: int
    days: list[date]
    series: list[CompareSeriesOut]


class BurstOut(BaseModel):
    start_day: date
    end_day: date
    duration_days: int
    peak_day: date
    peak_delta: int
    total_gained: int
    severity: float


class BurstsOut(BaseModel):
    items: list[BurstOut]
    active_burst: bool


class LeaderboardItemOut(BaseModel):
    rank: int
    owner: str
    name: str
    full_name: str
    language: str | None = None
    stars: int
    stars_per_day: float
    stars_gained: int


AlertKind = Literal["burst_started", "velocity_above", "stars_reached"]


class AlertRuleCreate(BaseModel):
    repository: str = Field(min_length=3, max_length=255, pattern=r"^[^/]+/[^/]+$")
    kind: AlertKind
    threshold: float | None = None
    window_days: int | None = None
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    kind: AlertKind | None = None
    threshold: float | None = None
    window_days: int | None = None
    enabled: bool | None = None


class AlertRuleOut(BaseModel):
    id: int
    repository: str
    kind: AlertKind
    threshold: float | None
    window_days: int | None
    enabled: bool
    last_value: float | None
    last_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime
````

## Verify

```bash
ruff check src/api/routes/alerts.py src/api/schemas.py src/api/app.py
```

## Commit

```bash
git add -- \
  src/api/app.py \
  src/api/routes/alerts.py \
  src/api/schemas.py
git commit -m 'feat: expose alert rule CRUD API'
```
