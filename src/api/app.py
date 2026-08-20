import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from api.routes import health, history, languages, repos, trends
from api.schemas import ErrorOut
from config import settings
from db.base import engine
from version import __version__

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
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
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.include_router(history.router, prefix=settings.api_prefix)
    app.include_router(repos.router, prefix=settings.api_prefix)
    app.include_router(trends.router, prefix=settings.api_prefix)
    app.include_router(languages.router, prefix=settings.api_prefix)
    app.include_router(health.router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": "GitHub Radar",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
            "repos": f"{settings.api_prefix}/repos",
            "trends": f"{settings.api_prefix}/trends",
            "languages": f"{settings.api_prefix}/languages",
        }

    @app.get("/{full_path:path}", include_in_schema=False)
    async def not_found(full_path: str) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ErrorOut(
                detail=f"Route not found: /{full_path}", code=404
            ).model_dump(),
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


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
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
