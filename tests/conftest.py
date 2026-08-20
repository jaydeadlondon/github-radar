import os
import tempfile
from pathlib import Path
import httpx
import pytest

_TMP_DIR = tempfile.mkdtemp(prefix="radar-tests-")
os.environ["RADAR_DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMP_DIR) / 'test.db'}"

from config import settings  # noqa: E402
from github.client import GitHubClient  # noqa: E402


@pytest.fixture(autouse=True)
def fast_retry_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_retries", 2)
    monkeypatch.setattr(settings, "backoff_base", 0.01)


@pytest.fixture
def client_factory():
    def _make(handler) -> GitHubClient:
        return GitHubClient(token="test-token", transport=httpx.MockTransport(handler))

    return _make


@pytest.fixture(scope="session", autouse=True)
async def _create_schema():
    from db.base import engine
    from db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables():
    from sqlalchemy import delete

    from db.base import SessionFactory
    from db.models import Repository, RepoSnapshot

    async with SessionFactory() as session:
        await session.execute(delete(RepoSnapshot))
        await session.execute(delete(Repository))
        await session.commit()


@pytest.fixture
async def db_session():
    from db.base import SessionFactory

    async with SessionFactory() as session:
        yield session


@pytest.fixture
async def api_client():
    import httpx

    from api.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
