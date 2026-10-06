"""End-to-end release tests for v1.0.

These tests exercise the shipped artefacts the way an operator does: the real
CLI through a subprocess against a throwaway SQLite database, the FastAPI app
through a test client, and the version/docs files that a release must keep in
sync.  They deliberately avoid the network and the repository database.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _cli(database: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "RADAR_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
        "RADAR_GITHUB_TOKEN": "",
        "PYTHONPATH": str(ROOT / "src"),
    }
    return subprocess.run(
        [sys.executable, "-m", "collector.cli", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _json(result: subprocess.CompletedProcess[str]) -> object:
    return json.loads(result.stdout)


def test_python_module_entry_point_runs_the_cli() -> None:
    result = _cli(Path("/tmp/never-created.db"), "version")
    assert result.returncode == 0, result.stderr
    assert re.search(r"\d+\.\d+\.\d+", result.stdout)


def test_full_database_lifecycle_end_to_end(tmp_path: Path) -> None:
    database = tmp_path / "e2e.db"

    missing = _cli(database, "db", "status", "-o", "json")
    assert missing.returncode == 0
    assert _json(missing)[0]["exists"] is False

    initialized = _cli(database, "init-db")
    assert initialized.returncode == 0, initialized.stderr
    assert database.exists()

    status = _json(_cli(database, "db", "status", "-o", "json"))[0]
    assert status["schema_present"] is True
    assert status["revision"] == status["head_revision"] == "0007"
    assert status["up_to_date"] is True

    assert _cli(database, "migrate", "--check").returncode == 0
    assert _cli(database, "doctor").returncode == 0

    # Seed a tracked repository with history and check every output format.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO repositories (id, full_name, description, html_url, "
            "language, tracking_enabled, tracking_paused) VALUES "
            "(1, 'acme/rocket', 'demo', 'https://github.com/acme/rocket', "
            "'Python', 1, 0)"
        )
        # Dates are relative to today so the default analytics windows see them.
        today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        connection.executemany(
            "INSERT INTO repo_snapshots (repo_id, stargazers_count, forks_count, "
            "open_issues_count, observed_at, quality_status) VALUES (1, ?, 1, 0, ?, 'accepted')",
            [
                (100 + day, (today - timedelta(days=19 - day)).strftime("%Y-%m-%d %H:%M:%S"))
                for day in range(20)
            ],
        )
        connection.commit()

    for fmt in ("table", "json", "csv"):
        listed = _cli(database, "repos", "list", "-o", fmt)
        assert listed.returncode == 0, listed.stderr
        assert "acme/rocket" in listed.stdout

    leaderboard = _cli(database, "leaderboard", "-o", "json")
    assert leaderboard.returncode == 0, leaderboard.stderr
    assert _json(leaderboard)[0]["full_name"] == "acme/rocket"

    # Backups, prune dry-run and restore all work on the live database.
    backup_dir = tmp_path / "backups"  # intentionally does not exist yet
    backed_up = _cli(database, "backup", str(backup_dir))
    assert backed_up.returncode == 0, backed_up.stderr
    backups = sorted(backup_dir.glob("radar-backup-*.db"))
    assert backups, "backup file was not created"
    # A backup is a single self-contained file, with no -wal/-shm companions.
    assert [path.name for path in backup_dir.iterdir()] == [backups[0].name]

    prune = _json(_cli(database, "prune", "--dry-run", "-o", "json"))[0]
    assert prune["dry_run"] is True
    assert prune["keep_days"] >= 1

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM repo_snapshots")
        connection.commit()
    restored = _cli(database, "restore", str(backups[0]), "--force", "--yes")
    assert restored.returncode == 0, restored.stderr
    with sqlite3.connect(database) as connection:
        remaining = connection.execute("SELECT count(*) FROM repo_snapshots").fetchone()[0]
    assert remaining == 20

    # A missing database is a documented exit code, not a crash.
    gone = _cli(tmp_path / "gone.db", "history", "acme/rocket", "-o", "json")
    assert gone.returncode == 4
    assert "Traceback" not in gone.stderr


def test_version_documents_agree() -> None:
    from version import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)

    pyproject = (ROOT / "pyproject.toml").read_text()
    declared = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    assert declared is not None and declared.group(1) == __version__

    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## [{__version__}]" in changelog

    snapshot = json.loads((ROOT / "docs" / "openapi-v1.json").read_text())
    assert snapshot["info"]["version"] == __version__


def test_release_documentation_is_present() -> None:
    for name in (
        "CHANGELOG.md",
        "docs/CONTRACT_AUDIT.md",
        "docs/DOMAIN_MODEL.md",
        "docs/API_V1.md",
        "docs/SECURITY.md",
    ):
        assert (ROOT / name).is_file(), name
    readme = (ROOT / "README.md").read_text()
    for heading in (
        "## Database lifecycle",
        "### Supported schema versions and upgrade path",
        "### Failed migrations",
        "### Data is never auto-deleted",
        "### Snapshot retention",
    ):
        assert heading in readme, heading


def _committed_mode(path: Path) -> str | None:
    """Return the mode git records for *path* (``100755``), or ``None``."""

    try:
        result = subprocess.run(
            ["git", "ls-files", "--stage", "--", path.relative_to(ROOT).as_posix()],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:  # pragma: no cover - git is not installed
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


def _load_release_check() -> Any:
    """Import ``scripts/release_check.py`` to test its command helpers."""

    spec = importlib.util.spec_from_file_location(
        "release_check", ROOT / "scripts" / "release_check.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_check_script_is_runnable() -> None:
    script = ROOT / "scripts" / "release_check.py"
    assert script.is_file()
    assert script.read_text().splitlines()[0].startswith("#!")
    if os.name == "posix" and not os.access(script, os.X_OK):
        # Checkouts that were copied rather than cloned (file sync tools,
        # zipped trees) lose the executable bit; the committed mode is the
        # contract the release relies on, so accept it and keep the run below.
        assert _committed_mode(script) == "100755", (
            "scripts/release_check.py is not executable; run "
            "`chmod +x scripts/release_check.py` (or `git checkout -- "
            "scripts/release_check.py` to restore the committed 0755 mode)"
        )
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "--skip-tests" in result.stdout


def test_release_check_script_is_marked_executable_in_git() -> None:
    mode = _committed_mode(ROOT / "scripts" / "release_check.py")
    if mode is None:
        pytest.skip("not a git checkout")
    assert mode == "100755", (
        "run `git update-index --chmod=+x scripts/release_check.py`"
    )


def test_release_check_uses_the_running_interpreter() -> None:
    """The venv directory is not always ``.venv`` - ``venv`` must work too."""

    module = _load_release_check()
    assert module.pytest_command() == [sys.executable, "-m", "pytest", "-q"]
    ruff = module.ruff_command()
    assert ruff[0] == sys.executable or Path(ruff[0]).is_file()
    assert ruff[1:] == ["check", "src", "tests", "scripts"]


def test_release_check_reports_a_missing_tool() -> None:
    module = _load_release_check()
    result = module._run(["/nonexistent/radar-release-tool"], capture_output=True, text=True)
    assert result.returncode == 127
    assert "radar-release-tool" in result.stderr


def test_database_file_is_not_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "radar.db", "*.db"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tracked == "", f"database files are tracked: {tracked}"


@pytest.mark.parametrize("path", ["docs/openapi-v1.json", "docs/API_V1.md"])
def test_api_contract_artifacts_exist(path: str) -> None:
    assert (ROOT / path).is_file()
