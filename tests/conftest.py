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


# Address returned for every webhook hostname during the test session. It must be
# a globally routable address: Python counts the RFC 5737 documentation ranges
# (198.51.100.0/24 and friends) as private/reserved, so the SSRF guard would
# reject them.
TEST_RESOLVED_ADDRESS = "1.1.1.1"


@pytest.fixture(autouse=True)
def deterministic_webhook_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never consult the host resolver from the test suite.

    The SSRF guard re-resolves webhook hostnames at delivery time. A machine
    whose DNS answers reserved names (``*.test``, ``*.example``) with ``0.0.0.0``
    or an internal address - NXDOMAIN hijacking by an ISP, a router or a
    corporate resolver - would otherwise block deliveries that tests only ever
    send through ``httpx.MockTransport``, and the failures would look like
    product bugs. Tests that need a specific answer (private address, empty
    resolution) patch ``security._resolve`` themselves and win over this
    fixture, because monkeypatch applies the later patch.
    """

    import ipaddress

    import security

    monkeypatch.setattr(
        security,
        "_resolve",
        lambda hostname: [ipaddress.ip_address(TEST_RESOLVED_ADDRESS)],
    )


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
    from db.models import (
        AlertDelivery,
        AlertEvent,
        AlertRule,
        JobLock,
        NotificationEndpoint,
        Repository,
        RepoSnapshot,
        SnapshotJob,
    )

    async with SessionFactory() as session:
        await session.execute(delete(AlertDelivery))
        await session.execute(delete(AlertEvent))
        await session.execute(delete(AlertRule))
        await session.execute(delete(NotificationEndpoint))
        await session.execute(delete(SnapshotJob))
        await session.execute(delete(JobLock))
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
