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
from observability import metrics
from version import __version__

logger = logging.getLogger(__name__)


def _dashboard_dir() -> Path:
    candidates = (
        Path.cwd() / "web",
        Path(__file__).resolve().parents[2] / "web",
    )
    for path in candidates:
        if path.is_dir():
            return path
    raise RuntimeError("Dashboard directory 'web' was not found")


class DashboardStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                request_id = (scope.get("state") or {}).get("request_id")
                return JSONResponse(
                    status_code=404,
                    content=ErrorOut(
                        detail=f"Not found: /{path}",
                        code=404,
                        type="not_found",
                        request_id=request_id,
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

    from db.base import optimize_database

    await optimize_database()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="GitHub Radar",
        description="Analytics service for tracking rising stars on GitHub.",
        version=__version__,
        lifespan=lifespan,
    )
    app.middleware("http")(request_logging)
    wildcard = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=not wildcard,
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
        "/",
        DashboardStaticFiles(directory=_dashboard_dir(), html=True),
        name="dashboard",
    )
    return app


def _error_type(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "auth_required",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
        502: "upstream_error",
        503: "unavailable",
    }.get(status_code, "error")


def _error_payload(request: Request, detail: str, status_code: int) -> dict:
    request_id = getattr(request.state, "request_id", None)
    return ErrorOut(
        detail=detail,
        code=status_code,
        type=_error_type(status_code),
        request_id=request_id,
    ).model_dump()


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.perf_counter()

    declared_length = _content_length(request)
    if declared_length is not None and declared_length > settings.max_request_bytes:
        response = JSONResponse(
            status_code=413,
            content=_error_payload(
                request,
                f"Request body exceeds RADAR_MAX_REQUEST_BYTES "
                f"({settings.max_request_bytes} bytes)",
                413,
            ),
        )
        response.headers["X-Request-ID"] = request_id
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        metrics.increment(
            "http_requests", labels={"method": request.method, "status": 413}
        )
        return response
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if request.url.path.startswith(settings.api_prefix):
        response.headers["X-API-Version"] = "v1"
        response.headers["X-API-Compatibility"] = "stable"
    metrics.increment(
        "http_requests",
        labels={"method": request.method, "status": response.status_code},
    )
    metrics.observe(
        "http_request_duration_seconds",
        duration_ms / 1000,
        labels={"method": request.method, "path": request.url.path},
    )
    logger.info(
        "http request",
        extra={
            "request_id": request_id,
            "operation": f"{request.method} {request.url.path}",
            "duration_ms": round(duration_ms, 2),
            "result": response.status_code,
        },
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
        content=_error_payload(request, detail, exc.status_code),
        headers=dict(getattr(exc, "headers", None) or {}),
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
        content=_error_payload(request, "Request validation failed", 422),
    )


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_error_payload(request, "Internal server error", 500),
    )
