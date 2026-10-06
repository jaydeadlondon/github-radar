#!/usr/bin/env python
"""End-to-end release check for GitHub Radar.

Runs the whole v1.0 release checklist against a throwaway SQLite database and a
throwaway dashboard data directory, then prints a table of results and exits
non-zero if any check fails::

    python scripts/release_check.py                 # from any virtualenv
    python scripts/release_check.py --skip-tests    # faster iteration

Nothing touches the repository database, no network access is required and no
GitHub token is needed.  Steps:

1. ``radar version`` and ``radar db status`` on a missing database.
2. ``radar init-db`` then ``radar db status`` (revision vs. head).
3. ``radar migrate --check`` on a current database.
4. Version consistency: ``version.py``, installed metadata, ``pyproject.toml``,
   the changelog and the OpenAPI snapshot agree.
5. API smoke test: create the app, hit ``/health``, ``/ready``, a v1 endpoint
   and the dashboard document.
6. CLI smoke test of every stable output format on an empty database.
7. Lint (``ruff``), the full pytest suite, the security audit, JS syntax and
   ``git diff --check``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Deliberately no sys.path manipulation: the check must report where the
# installed package actually lives. Adding src/ here would make the
# "imported from this checkout" check pass even with a stale install.

OK = "ok"
FAIL = "FAIL"


class Checker:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []
        self.failed = False

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((OK if ok else FAIL, name, detail))
        if not ok:
            self.failed = True
        print(f"[{OK if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))

    def report(self) -> None:
        passed = sum(1 for status, _, _ in self.results if status == OK)
        print(f"\n{passed}/{len(self.results)} checks passed")
        for status, name, detail in self.results:
            if status == FAIL:
                print(f"  failed: {name} — {detail}")


def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run *command*, turning a missing executable into a normal failure.

    ``FileNotFoundError`` from a tool that lives outside the running
    environment used to escape as a traceback and hide every other result.
    """

    try:
        return subprocess.run(command, **kwargs)
    except OSError as error:
        return subprocess.CompletedProcess(
            command, 127, "", f"{command[0]}: {error.strerror or error}"
        )


def _interpreter_tool(name: str) -> str | None:
    """Locate *name* next to ``sys.executable``, then on ``PATH``.

    The virtualenv directory has no fixed name - ``.venv``, ``venv`` and the
    system interpreter all happen - so a hardcoded ``.venv/bin/<tool>`` is a
    bug rather than a fallback.
    """

    beside = Path(sys.executable).parent / name
    if beside.is_file():
        return str(beside)
    return shutil.which(name)


def pytest_command() -> list[str]:
    """Run pytest with the interpreter that executes this script."""

    return [sys.executable, "-m", "pytest", "-q"]


def ruff_command() -> list[str]:
    """Run ruff from the running environment, or as an importable module."""

    tool = _interpreter_tool("ruff")
    if tool is not None:
        return [tool, "check", "src", "tests", "scripts"]
    return [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]


def _cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run the installed console script (the exact entry point users run)."""

    console = _interpreter_tool("radar")
    command = [console] if console else [sys.executable, "-m", "collector.cli"]
    return _run([*command, *args], cwd=ROOT, env=env, capture_output=True, text=True)


def _rows(payload: str) -> list[dict[str, object]]:
    """Read the stable JSON shape: a list of row objects."""

    import json

    document = json.loads(payload or "[]")
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)]
    items = document.get("rows") or document.get("items") or []
    return [row for row in items if isinstance(row, dict)]


def _python(env: dict[str, str], code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**env, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )


def _code_version() -> str:
    from version import __version__

    return __version__


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )
    return result.stdout.strip()


def check_checkout(checker: Checker) -> None:
    """Make every run state which revision produced the result.

    The most common way to see bogus failures is running a working tree that
    mixes files from several commits (or an older revision) with a newer venv.
    Printing the revision and comparing it with ``origin/<branch>`` turns that
    into a one-line diagnosis instead of a pytest archaeology session.
    """

    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    revision = _git("rev-parse", "--short", "HEAD")
    detached = branch == "HEAD"
    print(f"checkout: {branch if not detached else 'detached HEAD'} @ {revision}")

    if detached:
        checker.record(
            "checkout is on the release branch (not a detached HEAD)",
            False,
            "run `git checkout -f -B <branch> origin/<branch>` before validating",
        )
        return

    dirty = _git("status", "--porcelain", "--untracked-files=no")
    checker.record(
        "working tree has no modified tracked files",
        not dirty,
        dirty.splitlines()[0] if dirty else "",
    )

    remote_revision = _git("rev-parse", "--verify", "-q", f"origin/{branch}")
    if not remote_revision:
        checker.record(
            "branch is pushed to origin",
            False,
            f"origin/{branch} not found; push the branch or run from the release commit",
        )
        return
    same = remote_revision == _git("rev-parse", "HEAD")
    checker.record(
        "checkout matches origin/<branch>",
        same,
        ""
        if same
        else (
            f"HEAD is {revision} but origin/{branch} is "
            f"{remote_revision[:7]}; sync with "
            f"`git checkout -f -B {branch} origin/{branch}` before running the "
            "suite - otherwise the failures may describe code you no longer have"
        ),
    )


def check_import_locations(checker: Checker) -> None:
    """Every ``src`` module must come from this checkout.

    A non-editable ``pip install .`` leaves a stale copy in site-packages, and
    then ``pytest`` exercises code that is not in the working tree - the failure
    output then describes a revision nobody can find.
    """

    import importlib
    import importlib.metadata

    modules: dict[str, object] = {}
    try:
        for name in ("security", "alerts.webhook", "db.base"):
            modules[name] = importlib.import_module(name)
    except ImportError as exc:
        checker.record(
            "package is importable in this environment",
            False,
            f"{exc} - run `pip install -e \".[dev]\"`",
        )
        return

    print("imported from:")
    for name, module in modules.items():
        print(f"  {name:<16} {Path(module.__file__).resolve()}")

    outside = {
        name: str(Path(module.__file__).resolve())
        for name, module in modules.items()
        if not Path(module.__file__).resolve().is_relative_to(ROOT)
    }
    checker.record(
        "src modules are imported from this checkout",
        not outside,
        (
            "; ".join(f"{name} -> {path}" for name, path in outside.items())
            + ' - reinstall with `pip install -e ".[dev]"`'
            if outside
            else ""
        ),
    )

    editable_root = _editable_project_root()
    if editable_root is None:
        print("editable install: not detected (regular install)")
        return
    print(f"editable install points at: {editable_root}")
    checker.record(
        "editable install points at this checkout",
        editable_root == ROOT,
        (
            f"the venv is installed from {editable_root} but the check runs in "
            f"{ROOT}; reinstall or run the check from the installed checkout"
            if editable_root != ROOT
            else ""
        ),
    )


def _editable_project_root() -> Path | None:
    """Where ``pip install -e .`` was run, when that is how the package is set up."""

    import importlib.metadata
    import json

    try:
        distribution = importlib.metadata.distribution("github-radar")
    except importlib.metadata.PackageNotFoundError:
        return None
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return None
    url = json.loads(raw).get("url", "")
    if not url.startswith("file://"):
        return None
    return Path(url[len("file://") :]).resolve()


def check_version_consistency(checker: Checker) -> None:
    version = _code_version()
    checker.record(
        "version.py defines a release version",
        bool(re.fullmatch(r"\d+\.\d+\.\d+", version)),
        version,
    )

    installed = subprocess.run(
        [sys.executable, "-c", "import importlib.metadata as m; print(m.version('github-radar'))"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    checker.record(
        "installed metadata matches version.py",
        installed == version,
        f"installed={installed or 'n/a'} code={version}",
    )

    pyproject = (ROOT / "pyproject.toml").read_text()
    declared = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    checker.record(
        "pyproject.toml matches version.py",
        declared is not None and declared.group(1) == version,
        declared.group(1) if declared else "missing",
    )

    changelog = (ROOT / "CHANGELOG.md").read_text()
    checker.record(
        "CHANGELOG has an entry for the version",
        f"## [{version}]" in changelog,
        f"looking for ## [{version}]",
    )

    code = (
        "from api.app import create_app;"
        "print(create_app().openapi()['info']['version'])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    reported = result.stdout.strip()
    checker.record(
        "OpenAPI document reports the version",
        reported == version,
        reported or result.stderr.strip()[:120],
    )


def check_cli_database(checker: Checker, env: dict[str, str]) -> None:
    missing = _cli(env, "db", "status", "-o", "json")
    rows = _rows(missing.stdout)
    first = rows[0] if rows else {}
    checker.record(
        "db status reports a missing database without failing",
        missing.returncode == 0 and first.get("exists") in (False, "False", "no", 0),
        f"exit={missing.returncode}",
    )

    created = _cli(env, "init-db")
    checker.record("radar init-db succeeds", created.returncode == 0, created.stderr.strip()[:120])

    current = _cli(env, "migrate", "--check")
    checker.record("radar migrate --check is clean after init-db", current.returncode == 0)

    status = _cli(env, "db", "status", "-o", "json")
    rows = _rows(status.stdout)
    revision = rows[0].get("revision") if rows else None
    head = rows[0].get("head_revision") if rows else None
    checker.record(
        "schema revision equals head",
        bool(revision) and revision == head,
        f"revision={revision} head={head}",
    )

    # Only database-backed commands: the release check must work offline.
    for args in (
        ("db", "status", "-o", "table"),
        ("db", "status", "-o", "csv"),
        ("repos", "list", "-o", "json"),
        ("leaderboard", "-o", "csv"),
        ("prune", "--dry-run", "-o", "json"),
        ("version", "-o", "json"),
    ):
        result = _cli(env, *args)
        checker.record(
            f"radar {' '.join(args)} exits 0",
            result.returncode == 0,
            result.stderr.strip()[:120],
        )


API_SMOKE = """
from fastapi.testclient import TestClient

from api.app import create_app

with TestClient(create_app()) as client:
    checks = [
        ("GET /health", client.get("/health").status_code, (200, 503)),
        ("GET /ready", client.get("/ready").status_code, (200, 503)),
        ("GET /api/v1/repos", client.get("/api/v1/repos").status_code, (200,)),
        ("GET /api/v1/languages", client.get("/api/v1/languages").status_code, (200,)),
        ("dashboard assets", client.get("/app.js").status_code, (200,)),
    ]
    document = client.get("/")
    checks.append(
        ("GET / serves the dashboard", document.status_code, (200,))
    )
    has_title = "GitHub Radar" in document.text
for name, status, allowed in checks:
    print(f"{name}\t{status}\t{status in allowed}")
print(f"dashboard title\t{has_title}\t{has_title}")
"""


def check_api(checker: Checker, env: dict[str, str]) -> None:
    result = _python(env, API_SMOKE)
    if result.returncode != 0:
        checker.record("API smoke test", False, result.stderr.strip()[-200:])
        return
    for line in result.stdout.strip().splitlines():
        name, status, ok = line.split("\t")
        checker.record(f"API {name}", ok == "True", f"status={status}")


def check_static(checker: Checker) -> None:
    import json

    snapshot = json.loads((ROOT / "docs" / "openapi-v1.json").read_text())
    checker.record(
        "OpenAPI snapshot is versioned with the code",
        snapshot["info"]["version"] == _code_version(),
        snapshot["info"]["version"],
    )

    node = shutil.which("node")
    if node is None:
        checker.record("node available for JS syntax check", False, "node not found")
    else:
        for script in ("web/app.js", "web/charts.js"):
            result = subprocess.run(
                [node, "--check", script], cwd=ROOT, capture_output=True, text=True
            )
            checker.record(
                f"{script} parses", result.returncode == 0, result.stderr.strip()[:120]
            )

    result = subprocess.run(
        ["git", "diff", "--check"], cwd=ROOT, capture_output=True, text=True
    )
    checker.record("git diff --check", result.returncode == 0, result.stdout.strip()[:200])
    tracked = subprocess.run(
        ["git", "ls-files", "radar.db"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    checker.record("radar.db is not tracked", tracked == "", tracked)


def check_external(checker: Checker, skip_tests: bool) -> None:
    lint = _run(ruff_command(), cwd=ROOT, capture_output=True, text=True)
    detail = (lint.stdout or lint.stderr).strip().splitlines()[-1:] or [""]
    if "No module named ruff" in (lint.stderr or ""):
        detail = [
            'ruff is not installed in the running environment; run '
            '`pip install -e ".[dev]"`'
        ]
    checker.record("ruff check", lint.returncode == 0, detail[0][:120])

    if skip_tests:
        checker.record("pytest suite", True, "skipped")
    else:
        suite = _run(pytest_command(), cwd=ROOT, capture_output=True, text=True)
        tail = (suite.stdout or suite.stderr).strip().splitlines()[-1:] or [""]
        checker.record("pytest suite", suite.returncode == 0, tail[0][:120])

    audit_script = ROOT / "scripts" / "security_audit.sh"
    bash = shutil.which("bash")
    audit = _run(
        [bash, str(audit_script)] if bash else [str(audit_script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        # Audit the environment that is actually running the check.
        env={**os.environ, "PYTHON": sys.executable},
    )
    lines = (audit.stdout or audit.stderr).strip().splitlines()
    checker.record(
        "security audit (runtime dependencies)",
        audit.returncode == 0,
        lines[-1][:120] if lines else "",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true", help="skip pytest and ruff")
    parser.add_argument("--keep", action="store_true", help="keep the temporary database")
    args = parser.parse_args()

    temp = tempfile.mkdtemp(prefix="radar-release-")
    database = Path(temp) / "release.db"
    env = {
        **os.environ,
        "RADAR_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
        "RADAR_ENVIRONMENT": "development",
        # Never reach GitHub during the check.
        "RADAR_GITHUB_TOKEN": "",
    }
    env.pop("RADAR_API_AUTH_ENABLED", None)

    checker = Checker()
    print(f"release check: database at {database}")
    print(f"interpreter: {sys.executable}\n")
    try:
        check_checkout(checker)
        check_import_locations(checker)
        check_version_consistency(checker)
        check_cli_database(checker, env)
        check_api(checker, env)
        check_static(checker)
        check_external(checker, args.skip_tests)
    finally:
        checker.report()
        if not args.keep:
            shutil.rmtree(temp, ignore_errors=True)
        else:
            print(f"kept database at {database}")
    return 1 if checker.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
