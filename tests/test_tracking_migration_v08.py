from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_tracking_migration_is_additive_and_reversible(tmp_path: Path):
    database = tmp_path / "tracking-migration.db"
    env = {**os.environ, "RADAR_DATABASE_URL": f"sqlite+aiosqlite:///{database}"}
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
        repository_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(repositories)")
        }
        snapshot_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(repo_snapshots)")
        }
    assert {
        "tracking_enabled",
        "tracking_paused",
        "tracking_label",
        "last_successful_snapshot_at",
        "last_snapshot_attempt_at",
        "last_snapshot_error",
        "next_snapshot_at",
    } <= repository_columns
    assert {"quality_status", "quality_reason"} <= snapshot_columns

    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0003"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(database) as connection:
        repository_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(repositories)")
        }
    assert "tracking_enabled" not in repository_columns
