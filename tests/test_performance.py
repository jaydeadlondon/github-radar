"""Performance guardrails for the v1.0 release.

These tests seed a dataset far larger than a typical installation (tens of
repositories, months of daily snapshots), then assert two things: the hot reads
use the composite index from migration 0007, and they stay well inside a
generous time budget on a laptop-class machine.  Budgets are intentionally
loose so the suite never becomes flaky on slow CI, while still catching an
accidental O(n^2) or full-table-scan regression.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPOS = 40
DAYS = 240
HISTORY_QUERY = """
EXPLAIN QUERY PLAN
SELECT id, repo_id, observed_at, stargazers_count FROM repo_snapshots
WHERE repo_id = 1
  AND quality_status IN ('accepted', 'anomalous')
  AND observed_at >= '2000-01-01 00:00:00'
ORDER BY observed_at, id
"""
LATEST_QUERY = """
EXPLAIN QUERY PLAN
SELECT repo_id, max(observed_at) FROM repo_snapshots
WHERE quality_status IN ('accepted', 'anomalous')
GROUP BY repo_id
"""


@pytest.fixture
async def seeded_database() -> None:
    """Fill the test database with REPOS repositories x DAYS snapshots."""

    from sqlalchemy import insert

    from db.base import SessionFactory
    from db.models import Repository, RepoSnapshot

    start = datetime.now(UTC) - timedelta(days=DAYS)
    async with SessionFactory() as session:
        await session.execute(
            insert(Repository),
            [
                {
                    "id": repo_id,
                    "full_name": f"acme/repo-{repo_id}",
                    "description": "",
                    "html_url": f"https://github.com/acme/repo-{repo_id}",
                    "language": "Python",
                    "tracking_enabled": True,
                    "tracking_paused": False,
                }
                for repo_id in range(1, REPOS + 1)
            ],
        )
        await session.execute(
            insert(RepoSnapshot),
            [
                {
                    "repo_id": repo_id,
                    "stargazers_count": 1000 + repo_id * 10 + day * (5 + repo_id % 7),
                    "forks_count": day,
                    "open_issues_count": 0,
                    "observed_at": start + timedelta(days=day),
                    "quality_status": "accepted",
                }
                for repo_id in range(1, REPOS + 1)
                for day in range(DAYS)
            ],
        )
        await session.commit()


async def test_history_query_is_indexed(db_session, seeded_database: None) -> None:
    from sqlalchemy import text

    plan = " ".join(
        str(part)
        for row in (await db_session.execute(text(HISTORY_QUERY))).fetchall()
        for part in row
    )
    assert "SCAN repo_snapshots" not in plan, plan
    assert "USING INDEX" in plan, plan


async def test_latest_snapshot_aggregation_uses_the_covering_index(
    db_session, seeded_database: None
) -> None:
    """The dashboard's "latest snapshot per repository" read is index-only.

    SQLite only picks the covering index once the planner has statistics, which
    ``radar db optimize`` (``PRAGMA optimize``) maintains, so the test seeds and
    analyses the table exactly like a real installation.
    """

    from sqlalchemy import text

    await db_session.execute(text("ANALYZE"))
    plan = " ".join(
        str(part)
        for row in (await db_session.execute(text(LATEST_QUERY))).fetchall()
        for part in row
    )
    assert "ix_repo_snapshots_repo_quality_observed" in plan, plan
    assert "TEMP B-TREE" not in plan, plan


async def test_leaderboard_stays_within_budget(
    db_session, seeded_database: None
) -> None:
    from analytics.service import leaderboard

    started = time.perf_counter()
    total, items = await leaderboard(db_session, window_days=7, limit=15, offset=0)
    elapsed = time.perf_counter() - started

    assert total == REPOS
    assert len(items) == 15
    assert items[0][1].stars_per_day >= items[-1][1].stars_per_day
    assert elapsed < 5.0, f"leaderboard took {elapsed:.2f}s"


async def test_series_and_growth_stay_within_budget(
    db_session, seeded_database: None
) -> None:
    from analytics.service import repo_series
    from db.repositories import top_growth

    since = datetime.now(UTC) - timedelta(days=90)

    started = time.perf_counter()
    series = await repo_series(db_session, 1, history_days=90)
    series_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    ranked = await top_growth(db_session, since, limit=10)
    growth_elapsed = time.perf_counter() - started

    assert len(series) >= 80
    assert len(ranked) == 10
    assert series_elapsed < 2.0, f"repo_series took {series_elapsed:.2f}s"
    assert growth_elapsed < 5.0, f"top_growth took {growth_elapsed:.2f}s"


async def test_top_growth_matches_a_naive_scan(db_session, seeded_database: None) -> None:
    """The bounded two-query rewrite keeps the historic semantics."""

    from sqlalchemy import select

    from db.models import RepoSnapshot
    from db.repositories import ACCEPTED_QUALITY_STATUSES, top_growth

    since = datetime.now(UTC) - timedelta(days=60)
    ranked = await top_growth(db_session, since, limit=5)

    snapshots = (
        await db_session.scalars(
            select(RepoSnapshot)
            .where(
                RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES),
                RepoSnapshot.observed_at >= since,
            )
            .order_by(RepoSnapshot.repo_id, RepoSnapshot.observed_at, RepoSnapshot.id)
        )
    ).all()
    expected: dict[int, list[RepoSnapshot]] = {}
    for snapshot in snapshots:
        expected.setdefault(snapshot.repo_id, []).append(snapshot)
    naive = sorted(
        (
            (repo_id, rows[-1].stargazers_count - rows[0].stargazers_count)
            for repo_id, rows in expected.items()
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    assert [(repo.id, growth) for repo, growth in ranked] == naive[:5]
    assert ranked[0][0].latest_stargazers == expected[naive[0][0]][-1].stargazers_count


def test_sqlite_file_databases_use_wal() -> None:
    from sqlalchemy import create_engine

    from db.base import engine

    if engine.url.get_backend_name() != "sqlite":
        pytest.skip("SQLite specific tuning")
    path = Path(os.environ["RADAR_DATABASE_URL"].split("///")[-1])
    if not path.exists():
        pytest.skip("file-backed test database expected")

    sync = create_engine(f"sqlite:///{path}")
    with sync.connect() as connection:
        journal = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
    sync.dispose()
    assert str(journal).lower() == "wal"
    assert int(busy_timeout) >= 0


def test_migration_0007_is_additive_and_keeps_rows(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "upgrade.db"
    env = {**os.environ, "RADAR_DATABASE_URL": f"sqlite+aiosqlite:///{database}"}

    def alembic(revision: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    alembic("0006")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO repositories (id, full_name, description, html_url, "
            "language) VALUES (1, 'acme/legacy', 'old', "
            "'https://github.com/acme/legacy', 'Python')"
        )
        connection.execute(
            "INSERT INTO repo_snapshots (repo_id, stargazers_count, forks_count, "
            "open_issues_count, observed_at) VALUES (1, 42, 3, 0, "
            "'2026-09-20 12:00:00')"
        )
        connection.commit()

    alembic("head")
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT stargazers_count, quality_status FROM repo_snapshots"
        ).fetchall()
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert rows == [(42, "accepted")]
    assert "ix_repo_snapshots_repo_quality_observed" in indexes
