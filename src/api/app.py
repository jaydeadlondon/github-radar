import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes import (
    alerts,
    analytics,
    health,
    history,
    jobs,
    languages,
    operations,
    repos,
    trends,
)
from api.schemas import ErrorOut
from config import settings, validate_runtime_configuration
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
    validate_runtime_configuration()
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
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.include_router(history.router, prefix=settings.api_prefix)
    app.include_router(repos.router, prefix=settings.api_prefix)
    app.include_router(trends.router, prefix=settings.api_prefix)
    app.include_router(languages.router, prefix=settings.api_prefix)
    app.include_router(analytics.router, prefix=settings.api_prefix)
    app.include_router(alerts.router, prefix=settings.api_prefix)
    app.include_router(operations.router, prefix=settings.api_prefix)
    app.include_router(jobs.router, prefix=settings.api_prefix)
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
    if request.url.path.startswith(settings.api_prefix):
        response.headers["X-API-Version"] = "v1"
        response.headers["X-API-Compatibility"] = "stable"
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


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.info(
        "request validation failed",
        extra={
            "request_id": request.headers.get("X-Request-ID"),
            "operation": f"{request.method} {request.url.path}",
            "result": 422,
            "error_category": "request_validation",
        },
    )
    return JSONResponse(
        status_code=422,
        content=ErrorOut(detail="Request validation failed", code=422).model_dump(),
    )


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorOut(detail="Internal server error", code=500).model_dump(),
    )
