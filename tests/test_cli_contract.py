"""v1.0 CLI contract tests: output formats, exit codes and error streams."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from collector.cli import app
from config import settings
from db.lifecycle import REQUIRED_TABLES, head_revision
from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary

runner = CliRunner()
NOW = datetime.now(UTC)
DAY = timedelta(days=1)
SEED = [
    ("psf/requests", 500, "Python"),
    ("pallets/flask", 900, "Python"),
    ("golang/go", 700, "Go"),
]


def _seed() -> None:
    from db.base import SessionFactory

    async def _impl() -> None:
        for index, (full_name, stars, language) in enumerate(SEED):
            async with SessionFactory() as session:
                repo = await upsert_repository(
                    session,
                    RepoSummary(
                        id=index,
                        full_name=full_name,
                        description=f"About {full_name}",
                        html_url=f"https://github.com/{full_name}",
                        language=language,
                        stargazers_count=stars,
                        forks_count=10 + index,
                        created_at="2020-01-01T00:00:00Z",
                        pushed_at="2024-01-01T00:00:00Z",
                    ),
                )
                for offset, delta in [(4, 80), (3, 60), (2, 40), (1, 0)]:
                    await create_snapshot(
                        session,
                        repo.id,
                        stargazers=stars - delta * (index + 1),
                        forks=10,
                        observed_at=NOW - DAY * offset,
                    )
                await session.commit()

    asyncio.run(_impl())


def _make_lifecycle_database(path: Path, *, revision: str | None) -> None:
    """Create a minimal but valid GitHub Radar SQLite file."""

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE repositories (id INTEGER PRIMARY KEY, full_name TEXT)"
        )
        connection.execute(
            "CREATE TABLE repo_snapshots ("
            "id INTEGER PRIMARY KEY, repo_id INTEGER, observed_at TEXT)"
        )
        connection.execute("CREATE TABLE alert_events (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        for table in REQUIRED_TABLES:
            if table in {"repositories", "repo_snapshots", "alert_events", "alembic_version"}:
                continue
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        if revision is not None:
            connection.execute(
                "INSERT INTO alembic_version (version_num) VALUES (?)", (revision,)
            )
        for index in range(5):
            connection.execute(
                "INSERT INTO repositories (id, full_name) VALUES (?, ?)",
                (index, f"acme/repo{index}"),
            )
            for day in (5, 1):
                connection.execute(
                    "INSERT INTO repo_snapshots (repo_id, observed_at) VALUES (?, ?)",
                    (index, (NOW - DAY * day).strftime("%Y-%m-%d %H:%M:%S.%f")),
                )
        connection.commit()
    finally:
        connection.close()


def test_version_json_output() -> None:
    result = runner.invoke(app, ["version", "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["name"] == "github-radar"
    assert payload["version"]


def test_repos_list_json_is_machine_readable() -> None:
    _seed()
    result = runner.invoke(app, ["repos", "list", "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)  # stdout must be pure JSON
    assert {row["repository"] for row in payload} == {name for name, _, _ in SEED}
    for row in payload:
        assert row["status"] == "healthy"
        assert row["snapshot_count"] == 4
        assert row["last_successful_snapshot_at"].endswith("Z")


def test_repos_list_csv_has_stable_header() -> None:
    _seed()
    result = runner.invoke(app, ["repos", "list", "--output", "csv"])
    assert result.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    assert list(rows[0]) == [
        "repository",
        "status",
        "label",
        "snapshot_count",
        "last_successful_snapshot_at",
        "last_snapshot_error",
    ]
    assert len(rows) == 3


def test_leaderboard_csv_and_json_agree() -> None:
    _seed()
    csv_result = runner.invoke(app, ["leaderboard", "--output", "csv", "--window", "7"])
    json_result = runner.invoke(app, ["leaderboard", "--output", "json", "--window", "7"])
    assert csv_result.exit_code == 0
    assert json_result.exit_code == 0

    csv_rows = list(csv.DictReader(io.StringIO(csv_result.stdout)))
    json_rows = json.loads(json_result.stdout)
    assert [row["full_name"] for row in csv_rows] == [
        row["full_name"] for row in json_rows
    ]
    assert csv_rows[0]["full_name"] == "golang/go"


def test_unknown_output_format_is_a_usage_error() -> None:
    result = runner.invoke(app, ["leaderboard", "--output", "yaml"])
    assert result.exit_code == 2
    assert "unsupported output format" in result.stderr
    assert result.stdout == ""


def test_global_output_flag_is_used_as_default() -> None:
    result = runner.invoke(app, ["--output", "json", "version"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["name"] == "github-radar"


def test_quiet_suppresses_status_lines_only() -> None:
    loud = runner.invoke(app, ["snapshot"])
    quiet = runner.invoke(app, ["--quiet", "snapshot"])
    assert loud.exit_code == 0
    assert quiet.exit_code == 0
    assert quiet.stdout == ""
    assert "No tracked repositories" in loud.stdout


def test_missing_database_exits_with_code_four(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "database_url", f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}"
    )
    result = runner.invoke(app, ["history", "psf/requests"])
    assert result.exit_code == 4
    assert "radar init-db" in result.stderr
    assert result.stdout == ""


def test_doctor_and_db_status_on_missing_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "database_url", f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}"
    )
    status = runner.invoke(app, ["db", "status", "--output", "json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)[0]
    assert payload["exists"] is False
    assert payload["schema_present"] is False

    doctor = runner.invoke(app, ["doctor", "--output", "json"])
    assert doctor.exit_code == 1  # the missing database is an error-level check
    checks = {row["check"]: row for row in json.loads(doctor.stdout)}
    assert checks["database"]["status"] == "error"


def test_db_lifecycle_commands(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "radar.db"
    revision = head_revision()
    _make_lifecycle_database(database, revision=revision)
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{database}")

    status = runner.invoke(app, ["db", "status", "--output", "json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)[0]
    assert payload["exists"] is True
    assert payload["repositories"] == 5
    assert payload["snapshots"] == 10

    if revision:
        check = runner.invoke(app, ["migrate", "--check", "--output", "json"])
        assert check.exit_code == 0
        assert json.loads(check.stdout)["up_to_date"] is True

    backup_path = tmp_path / "backup.db"
    backup = runner.invoke(app, ["backup", str(backup_path), "--output", "json"])
    assert backup.exit_code == 0
    assert backup_path.is_file()
    assert json.loads(backup.stdout)["repositories"] == 5

    # Pruning keeps the newest snapshot of every repository.
    pruned = runner.invoke(
        app,
        ["prune", "--keep-days", "1", "--yes", "--output", "json"],
        catch_exceptions=False,
    )
    assert pruned.exit_code == 0
    assert json.loads(pruned.stdout)[0]["snapshots"] == 5

    dry_run = runner.invoke(
        app, ["prune", "--keep-days", "1", "--dry-run", "--output", "json"]
    )
    assert json.loads(dry_run.stdout)[0]["snapshots"] == 0

    restore = runner.invoke(
        app, ["restore", str(backup_path), "--force", "--yes", "--output", "json"]
    )
    assert restore.exit_code == 0
    restored = json.loads(restore.stdout)
    assert restored["snapshots"] == 10
    assert restored["safety_backup"]


def test_restore_rejects_a_non_sqlite_file(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "radar.db"
    _make_lifecycle_database(database, revision=head_revision())
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{database}")
    broken = tmp_path / "broken.db"
    broken.write_text("definitely not sqlite")

    result = runner.invoke(app, ["restore", str(broken), "--force", "--yes"])
    assert result.exit_code == 2
    assert "not a readable SQLite database" in result.stderr


def test_destructive_prompt_requires_yes_without_tty(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "radar.db"
    _make_lifecycle_database(database, revision=head_revision())
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{database}")
    backup_path = tmp_path / "backup.db"
    assert runner.invoke(app, ["backup", str(backup_path)]).exit_code == 0

    result = runner.invoke(app, ["restore", str(backup_path), "--force"])
    assert result.exit_code == 2
    assert "--yes" in result.stderr
