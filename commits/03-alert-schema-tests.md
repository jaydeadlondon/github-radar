# Commit 03 — test: cover alert schema migration and relationships

Reference implementation commit: `40049011644c28dd4a37533765ed9aa5cdab8983`
Apply after: `Commit 02`

## Goal

Verify model relationships, fingerprint uniqueness, retention behavior, timestamps, and migration upgrade/downgrade.

## Files

### `tests/conftest.py`

Replace this file with the complete post-commit content below.

````python
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
    from db.models import AlertEvent, AlertRule, Repository, RepoSnapshot

    async with SessionFactory() as session:
        await session.execute(delete(AlertEvent))
        await session.execute(delete(AlertRule))
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
````

### `tests/test_alert_models.py`

Create this file with the complete content below.

````python
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import AlertEvent, AlertRule
from db.repositories import upsert_repository
from github.models import RepoSummary


def _summary(full_name: str = "acme/rocket") -> RepoSummary:
    return RepoSummary(
        id=1,
        full_name=full_name,
        description="Fast",
        html_url=f"https://github.com/{full_name}",
        language="Python",
        stargazers_count=100,
        forks_count=1,
    )


async def _rule_and_event(db_session):
    repo = await upsert_repository(db_session, _summary())
    rule = AlertRule(
        repository=repo,
        kind="stars_reached",
        threshold=1000,
        enabled=True,
    )
    db_session.add(rule)
    await db_session.flush()
    event = AlertEvent(
        rule_id=rule.id,
        repo_id=repo.id,
        repository_full_name=repo.full_name,
        kind=rule.kind,
        fingerprint="milestone:1000",
        title="Star milestone reached",
        message="acme/rocket reached 1,000 stars",
        current_value=1001,
        threshold=1000,
    )
    db_session.add(event)
    await db_session.commit()
    return repo, rule, event


async def test_alert_rule_and_event_relationships(db_session) -> None:
    repo, rule, event = await _rule_and_event(db_session)

    stored_rule = await db_session.get(AlertRule, rule.id)
    stored_event = await db_session.get(AlertEvent, event.id)

    assert stored_rule is not None
    assert stored_rule.repository.full_name == repo.full_name
    assert stored_event is not None
    assert stored_event.rule_id == rule.id
    assert stored_event.delivery_status == "inbox_only"
    assert stored_event.acknowledged_at is None


async def test_event_fingerprint_is_unique_per_rule(db_session) -> None:
    repo, rule, event = await _rule_and_event(db_session)
    duplicate = AlertEvent(
        rule_id=rule.id,
        repo_id=repo.id,
        repository_full_name=repo.full_name,
        kind=rule.kind,
        fingerprint=event.fingerprint,
        title=event.title,
        message=event.message,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_events_survive_rule_deletion(db_session) -> None:
    _repo, rule, event = await _rule_and_event(db_session)
    event_id = event.id

    await db_session.delete(rule)
    await db_session.commit()
    db_session.expire_all()

    stored = await db_session.get(AlertEvent, event_id)
    assert stored is not None
    assert stored.rule_id is None


async def test_events_survive_repository_deletion(db_session) -> None:
    repo, _rule, event = await _rule_and_event(db_session)
    event_id = event.id

    await db_session.delete(repo)
    await db_session.commit()
    db_session.expire_all()

    stored = await db_session.get(AlertEvent, event_id)
    assert stored is not None
    assert stored.repo_id is None
    assert stored.rule_id is None
    assert stored.repository_full_name == "acme/rocket"


async def test_alert_timestamps_are_populated(db_session) -> None:
    _repo, rule, event = await _rule_and_event(db_session)
    assert isinstance(rule.created_at, datetime)
    assert isinstance(event.created_at, datetime)
    # SQLite returns naive values for timezone-aware columns; callers normalize at boundaries.
    assert event.created_at.replace(tzinfo=UTC).tzinfo is UTC


def test_alert_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    env = {
        **os.environ,
        "RADAR_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
    }
    root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert {"repositories", "repo_snapshots", "alert_rules", "alert_events"} <= tables
    assert "ix_alert_rules_repo_id_enabled" in indexes
    assert "ix_alert_events_acknowledged_created" in indexes

    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0002"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "alert_rules" not in tables
    assert "alert_events" not in tables
    assert {"repositories", "repo_snapshots"} <= tables
````

## Verify

```bash
pytest -q tests/test_alert_models.py
ruff check tests/test_alert_models.py tests/conftest.py
```

## Commit

```bash
git add -- \
  tests/conftest.py \
  tests/test_alert_models.py
git commit -m 'test: cover alert schema migration and relationships'
```
