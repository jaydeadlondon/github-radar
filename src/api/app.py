import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from config import settings
from db.base import engine
from version import __version__
from api.routes import history, repos, trends

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(repos.router, prefix=settings.api_prefix)
    app.include_router(history.router, prefix=settings.api_prefix)
    app.include_router(trends.router, prefix=settings.api_prefix)

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
        )

    return app
