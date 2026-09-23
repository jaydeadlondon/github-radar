from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _alembic(root: Path, database: Path, revision: str) -> None:
    env = {**os.environ, "RADAR_DATABASE_URL": f"sqlite+aiosqlite:///{database}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_v07_database_upgrades_without_losing_history(tmp_path: Path) -> None:
    database = tmp_path / "v07.db"
    root = Path(__file__).resolve().parents[1]
    _alembic(root, database, "0003")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO repositories "
            "(id, full_name, description, html_url, language) "
            "VALUES (1, 'acme/legacy', 'old', 'https://github.com/acme/legacy', 'Python')"
        )
        connection.execute(
            "INSERT INTO repo_snapshots "
            "(repo_id, stargazers_count, forks_count, open_issues_count, observed_at) "
            "VALUES (1, 10, 2, 1, '2026-09-19 12:00:00')"
        )
        connection.commit()

    _alembic(root, database, "head")
    with sqlite3.connect(database) as connection:
        repository = connection.execute(
            "SELECT full_name, tracking_enabled FROM repositories WHERE id = 1"
        ).fetchone()
        snapshot = connection.execute(
            "SELECT stargazers_count, quality_status FROM repo_snapshots WHERE repo_id = 1"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert repository == ("acme/legacy", 1)
    assert snapshot == (10, "accepted")
    assert {
        "job_locks",
        "snapshot_jobs",
        "notification_endpoints",
        "alert_deliveries",
    } <= tables
