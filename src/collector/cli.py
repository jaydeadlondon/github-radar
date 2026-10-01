from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from cli_output import (
    Column,
    emit_document,
    emit_rows,
    parse_output,
    to_jsonable,
)
from config import ConfigurationError
from exit_codes import (
    ConfigurationFailure,
    DatabaseUnavailableError,
    ExitCode,
    RadarError,
    UsageError,
)
from github.client import GitHubClient
from github.errors import GitHubError
from github.models import RepoSummary
from tracking.service import TrackingError
from version import __version__

app = typer.Typer(
    name="radar",
    help="GitHub Radar — track rising stars on GitHub.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)
_state: dict[str, object] = {"quiet": False, "output": None}
alerts_app = typer.Typer(
    help="Manage alert rules and the alert inbox.", no_args_is_help=True
)
app.add_typer(alerts_app, name="alerts")
repos_app = typer.Typer(
    help="Manage repositories and their tracking state.", no_args_is_help=True
)
app.add_typer(repos_app, name="repos")
notifications_app = typer.Typer(
    help="Manage webhook notification endpoints.", no_args_is_help=True
)
app.add_typer(notifications_app, name="notifications")


def _fail(message: str, code: ExitCode = ExitCode.ERROR) -> None:
    """Print an error to stderr and exit with the documented code."""

    err_console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(code)


def _info(message: str) -> None:
    """Print a status line, unless ``--quiet`` was requested."""

    if not _state["quiet"]:
        console.print(message)


def _resolve_output(local: str | None) -> str:
    """Merge a command-level ``--output`` with the global default."""

    value = local or _state["output"] or "table"
    try:
        return parse_output(str(value))
    except UsageError as exc:
        _fail(str(exc), exc.exit_code)


CLI_FAILURES = (
    RadarError,
    ConfigurationError,
    GitHubError,
    TrackingError,
)


def _translate_error(exc: BaseException) -> None:
    """Map a known failure to its documented exit code."""

    if isinstance(exc, (ConfigurationFailure, ConfigurationError)):
        _fail(str(exc), ExitCode.CONFIG)
    elif isinstance(exc, DatabaseUnavailableError):
        _fail(str(exc), ExitCode.DATABASE)
    elif isinstance(exc, RadarError):
        _fail(str(exc), exc.exit_code)
    else:
        _fail(str(exc), ExitCode.ERROR)


def _run_sync(fn: Callable[[], None]) -> None:
    """Run a synchronous command body with the shared error contract."""

    try:
        fn()
    except CLI_FAILURES as exc:
        _translate_error(exc)


def _run_async(fn: Callable[[], Awaitable[None]]) -> None:
    async def _wrapper() -> None:
        try:
            await fn()
        except CLI_FAILURES as exc:
            _translate_error(exc)

    asyncio.run(_wrapper())


def _require_database() -> None:
    """Fail with exit code 4 when the configured database is unusable."""

    from db.lifecycle import require_database

    try:
        require_database()
    except CLI_FAILURES as exc:
        _translate_error(exc)


def _abort(message: str = "Aborted.") -> None:
    """Stop a destructive command without pretending it failed."""

    err_console.print(f"[yellow]{message}[/yellow]")
    raise typer.Exit(ExitCode.INTERRUPTED)


def _warn_missing_token() -> None:
    """Warn (on stderr) when GitHub is used anonymously."""

    from config import settings

    if not settings.github_token:
        err_console.print(
            "[yellow]Warning:[/yellow] RADAR_GITHUB_TOKEN is not configured; "
            "GitHub requests run anonymously and are limited to 60 requests/hour."
        )


@app.callback()
def main(
    no_color: bool = typer.Option(
        False, "--no-color", help="Disable ANSI colors and styling."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress status messages (data output is kept)."
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Default output format for read commands: table, json or csv.",
    ),
) -> None:
    """GitHub Radar — track rising stars on GitHub."""

    global console, err_console
    if no_color:
        console = Console(no_color=True, highlight=False)
        err_console = Console(stderr=True, no_color=True, highlight=False)
    _state["quiet"] = quiet
    if output is not None:
        try:
            _state["output"] = parse_output(output)
        except UsageError as exc:
            _fail(str(exc), exc.exit_code)


def _alembic_ini_path() -> Path:
    candidates = (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "alembic.ini not found. Run the command from the project root."
    )


@app.command()
def version(
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table or json."
    ),
) -> None:
    """Print the installed version."""

    resolved = _resolve_output(output)
    if resolved == "json":
        emit_document({"name": "github-radar", "version": __version__}, "json")
    elif resolved == "csv":
        _fail("`radar version` supports table or json output only", ExitCode.USAGE)
    else:
        console.print(f"github-radar {__version__}")


@app.command("init-db")
def init_db(
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table or json."
    ),
) -> None:
    """Create the schema for a new database and stamp the current revision.

    Schema creation only happens when this command is called explicitly; the API
    and the worker never migrate a database on startup.
    """

    resolved = _resolve_output(output)

    async def _create_schema() -> None:
        from db.base import engine
        from db.models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    _run_async(_create_schema)

    # Alembic drives its own event loop, so stamping runs after ours: the new
    # schema is recorded at head and `radar migrate` can upgrade it later.
    from alembic.config import Config

    from alembic import command
    from db.lifecycle import database_state

    command.stamp(Config(str(_alembic_ini_path())), "head")
    state = database_state()
    payload = {
        "status": "initialized",
        "location": state.location,
        "revision": state.revision,
        "repository_count": state.repository_count,
    }
    if resolved == "json":
        emit_document(payload, "json")
    else:
        _info(
            f"[green]Database initialized at {state.location} "
            f"(revision {state.revision}).[/green]"
        )


@app.command()
def migrate(
    revision: str = typer.Option(
        "head", "--revision", help="Alembic revision to apply."
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Report the migration state without changing the database.",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table or json."
    ),
) -> None:
    """Upgrade an existing database to a revision (explicit, never automatic)."""

    resolved = _resolve_output(output)

    from db.lifecycle import database_state, require_database

    state = database_state()
    if check:
        payload = {
            "location": state.location,
            "exists": state.exists,
            "schema_present": state.schema_present,
            "current_revision": state.revision,
            "head_revision": state.head_revision,
            "up_to_date": state.migrations_current,
        }
        if resolved == "json":
            emit_document(payload, "json")
        else:
            emit_rows(
                [
                    {
                        "location": state.location,
                        "schema_present": state.schema_present,
                        "current_revision": state.revision,
                        "head_revision": state.head_revision,
                        "up_to_date": state.migrations_current,
                    }
                ],
                (
                    Column("location", "Database"),
                    Column("schema_present", "Schema"),
                    Column("current_revision", "Current revision"),
                    Column("head_revision", "Head revision"),
                    Column("up_to_date", "Up to date"),
                ),
                "table",
                title="Migration state",
                empty_message="No database state available.",
                console=console,
            )
        if not state.migrations_current:
            raise typer.Exit(ExitCode.DATABASE)
        return

    require_database()
    from alembic.config import Config

    from alembic import command

    alembic_config = Config(str(_alembic_ini_path()))
    try:
        command.upgrade(alembic_config, revision)
    except Exception as exc:
        err_console.print(
            f"[red]Error:[/red] migration failed: {exc}\n"
            f"Current revision: {state.revision}. The database was not "
            f"advanced past the last successful revision; inspect the log, fix the "
            f"cause and re-run `radar migrate`. Restore from `radar backup` if "
            f"the schema is inconsistent."
        )
        raise typer.Exit(ExitCode.DATABASE) from exc
    updated = database_state()
    if resolved == "json":
        emit_document(
            {
                "status": "migrated",
                "location": updated.location,
                "revision": updated.revision,
                "head_revision": updated.head_revision,
            },
            "json",
        )
    else:
        _info(
            f"[green]Database migrated to {revision} "
            f"(revision {updated.revision}).[/green]"
        )


db_app = typer.Typer(
    help="Inspect the database, its schema revision and its contents.",
    no_args_is_help=True,
)
app.add_typer(db_app, name="db")


def _state_row(state, *, label: str = "database") -> dict[str, object]:
    return {
        "location": state.location or state.url,
        "backend": state.backend,
        "exists": state.exists,
        "schema_present": state.schema_present,
        "revision": state.revision,
        "head_revision": state.head_revision,
        "up_to_date": state.migrations_current,
        "size_bytes": state.size_bytes,
        "repositories": state.repository_count,
        "snapshots": state.snapshot_count,
        "alert_events": state.alert_event_count,
        "detail": state.detail,
    }


_DB_COLUMNS: tuple[Column, ...] = (
    Column("location", "Database"),
    Column("backend", "Backend"),
    Column("exists", "Exists"),
    Column("schema_present", "Schema"),
    Column("revision", "Revision"),
    Column("head_revision", "Head"),
    Column("up_to_date", "Up to date"),
    Column("repositories", "Repositories", align="right"),
    Column("snapshots", "Snapshots", align="right"),
    Column("alert_events", "Alert events", align="right"),
    Column("size_bytes", "Size (bytes)", align="right"),
    Column("detail", "Notes"),
)
_DB_TABLE_KEYS = (
    "revision",
    "head_revision",
    "up_to_date",
    "repositories",
    "snapshots",
    "size_bytes",
    "location",
)
_DB_TABLE_COLUMNS: tuple[Column, ...] = tuple(
    column for column in _DB_COLUMNS if column.key in _DB_TABLE_KEYS
)
_DB_CSV_COLUMNS: tuple[Column, ...] = _DB_COLUMNS


@db_app.command("status")
def db_status(
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Show database location, schema revision and row counts."""

    from db.lifecycle import database_state

    resolved = _resolve_output(output)
    emit_rows(
        [_state_row(database_state())],
        _DB_TABLE_COLUMNS if resolved == "table" else _DB_CSV_COLUMNS,
        resolved,
        title="Database status",
        empty_message="No database status available.",
        console=console,
    )


@app.command()
def backup(
    destination: str | None = typer.Argument(
        None, help="Backup file or directory (default: ./radar-backup-<timestamp>.db)."
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table or json."
    ),
) -> None:
    """Write a consistent copy of the SQLite database."""

    def _command() -> None:
        from db.lifecycle import backup_database

        resolved = _resolve_output(output)
        result = backup_database(destination)
        payload = {
            "status": "backed_up",
            "source": result.source,
            "destination": result.destination,
            "size_bytes": result.size_bytes,
            "revision": result.revision,
            "repositories": result.repository_count,
            "snapshots": result.snapshot_count,
            "created_at": result.created_at,
        }
        if resolved == "json":
            emit_document(payload, "json")
        else:
            _info(
                f"[green]Backup written to {result.destination} "
                f"({result.size_bytes} bytes, revision {result.revision}).[/green]"
            )

    _run_sync(_command)


@app.command()
def restore(
    source: str = typer.Argument(..., help="Backup file created by `radar backup`."),
    destination: str | None = typer.Option(
        None, "--destination", help="Target database path (default: configured URL)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Replace an existing database without prompting."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    no_backup: bool = typer.Option(
        False,
        "--no-safety-backup",
        help="Do not keep a copy of the database that is being replaced.",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table or json."
    ),
) -> None:
    """Replace the configured database with a validated backup copy."""

    def _command() -> None:
        from db.lifecycle import database_state, restore_database

        resolved = _resolve_output(output)
        state = database_state()
        target = destination or state.location or state.url
        if state.exists and not force:
            _fail(
                f"destination database already exists: {target} (pass --force to replace it)",
                ExitCode.USAGE,
            )
        if state.exists and not yes and not _confirm(
            f"Replace the database at {target} with {source}?"
        ):
            _abort()
        result = restore_database(
            source,
            destination,
            force=True,
            safety_backup=not no_backup,
        )
        payload = {
            "status": "restored",
            "source": result.source,
            "destination": result.destination,
            "safety_backup": result.safety_backup,
            "revision": result.revision,
            "repositories": result.repository_count,
            "snapshots": result.snapshot_count,
        }
        if resolved == "json":
            emit_document(payload, "json")
        else:
            message = f"[green]Restored {result.destination} from {result.source}.[/green]"
            if result.safety_backup:
                message += f" Previous database kept at {result.safety_backup}."
            _info(message)

    _run_sync(_command)


@app.command()
def prune(
    keep_days: int = typer.Option(
        400, "--keep-days", min=1, help="Keep snapshots newer than this many days."
    ),
    keep_min_per_repo: int = typer.Option(
        1,
        "--keep-min-per-repo",
        min=0,
        help="Always keep the newest N snapshots of every repository.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be deleted without deleting."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Delete snapshot history older than a retention window (explicit only)."""

    def _command() -> None:
        from db.lifecycle import prune_snapshots

        resolved = _resolve_output(output)
        if not dry_run and not yes:
            if not _confirm(f"Delete snapshots older than {keep_days} days?"):
                _abort()
        result = prune_snapshots(
            keep_days,
            keep_min_per_repo=keep_min_per_repo,
            dry_run=dry_run,
        )
        rows = [
            {
                "keep_days": result.keep_days,
                "keep_min_per_repo": result.keep_min_per_repo,
                "dry_run": result.dry_run,
                "cutoff": result.cutoff,
                "snapshots": result.deleted_snapshots,
                "repositories": result.affected_repositories,
                "oldest_kept_at": result.oldest_kept_at,
            }
        ]
        emit_rows(
            rows,
            (
                Column("dry_run", "Dry run"),
                Column("keep_days", "Keep days", align="right"),
                Column("keep_min_per_repo", "Min per repo", align="right"),
                Column("cutoff", "Cutoff (UTC)"),
                Column("snapshots", "Snapshots", align="right"),
                Column("repositories", "Repositories", align="right"),
                Column("oldest_kept_at", "Oldest kept (UTC)"),
            ),
            resolved,
            title="Prune plan" if dry_run else "Prune result",
            empty_message="Nothing to prune.",
            console=console,
        )
        if resolved == "table":
            verb = "would be deleted" if dry_run else "deleted"
            _info(
                f"[green]{result.deleted_snapshots} snapshot(s) {verb} "
                f"across {result.affected_repositories} repository(-ies).[/green]"
            )

    _run_sync(_command)


@app.command()
def doctor(
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Diagnose configuration, database, migrations and dashboard assets."""

    def _command() -> None:
        checks = _run_doctor()
        resolved = _resolve_output(output)
        rows = [
            {"check": name, "status": status, "detail": detail}
            for name, status, detail in checks
        ]
        emit_rows(
            rows,
            (
                Column("check", "Check"),
                Column("status", "Status"),
                Column("detail", "Detail"),
            ),
            resolved,
            title="radar doctor",
            empty_message="No checks ran.",
            console=console,
        )
        failures = [row for row in rows if row["status"] == "error"]
        if failures:
            raise typer.Exit(ExitCode.ERROR)

    _run_sync(_command)


def _run_doctor() -> list[tuple[str, str, str]]:
    """Return ``(check, status, detail)`` rows used by ``radar doctor``."""

    import sys

    from config import ConfigurationError, configuration_warnings, validate_runtime_configuration
    from db.lifecycle import database_state

    checks: list[tuple[str, str, str]] = []
    checks.append(
        ("python", "ok" if sys.version_info >= (3, 11) else "error", sys.version.split()[0])
    )

    try:
        validate_runtime_configuration()
        warnings = configuration_warnings()
        checks.append(
            (
                "configuration",
                "warn" if warnings else "ok",
                "; ".join(warnings) if warnings else "no warnings",
            )
        )
    except (ConfigurationError, ValueError) as exc:
        checks.append(("configuration", "error", str(exc)))

    from config import settings

    checks.append(
        (
            "github_token",
            "ok" if settings.github_token else "warn",
            "configured" if settings.github_token else "not configured (anonymous rate limits)",
        )
    )

    state = database_state()
    if not state.exists:
        checks.append(
            (
                "database",
                "error",
                f"not found at {state.location}; run `radar init-db` or `radar migrate`",
            )
        )
    elif not state.schema_present:
        checks.append(
            ("database", "error", f"{state.location}: {state.detail or 'no schema'}")
        )
    elif not state.migrations_current:
        checks.append(
            (
                "migrations",
                "warn",
                f"revision {state.revision} != head {state.head_revision}; run `radar migrate`",
            )
        )
    else:
        checks.append(("database", "ok", f"{state.location} (revision {state.revision})"))
        checks.append(("migrations", "ok", str(state.revision)))

    if state.location:
        from pathlib import Path

        parent = Path(state.location).parent
        writable = parent.is_dir() and _can_write(parent)
        checks.append(
            (
                "database_directory",
                "ok" if writable else "error",
                f"{parent} is {'writable' if writable else 'not writable'}",
            )
        )

    dashboard = _dashboard_directory()
    checks.append(
        (
            "dashboard_assets",
            "ok" if dashboard else "error",
            str(dashboard) if dashboard else "web/ directory not found",
        )
    )

    if settings.alert_webhook_url:
        from security import UnsafeURL, validate_webhook_url

        try:
            validate_webhook_url(settings.alert_webhook_url)
            checks.append(("webhook_url", "ok", "configured webhook URL is allowed"))
        except UnsafeURL as exc:
            checks.append(("webhook_url", "error", str(exc)))
    else:
        checks.append(("webhook_url", "ok", "no legacy webhook URL configured"))

    checks.append(
        (
            "api_auth",
            "ok" if settings.api_auth_enabled else "warn",
            "enabled" if settings.api_auth_enabled else "disabled (development default)",
        )
    )
    return checks


def _can_write(path) -> bool:
    import os

    return os.access(path, os.W_OK)


def _dashboard_directory() -> Path | None:
    from pathlib import Path as _Path

    for candidate in (
        _Path.cwd() / "web",
        _Path(__file__).resolve().parents[2] / "web",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _confirm(prompt: str) -> bool:
    """Ask for confirmation, refusing to guess in non-interactive mode.

    A shell without a TTY cannot answer prompts, so the command fails with the
    usage code and tells the caller to pass ``--yes`` instead of hanging or
    assuming an answer.
    """

    import sys

    if not sys.stdin.isatty():
        _fail(
            f"{prompt} Refusing to continue without --yes in a non-interactive shell.",
            ExitCode.USAGE,
        )
    return typer.confirm(prompt, default=False, abort=False)


@app.command()
def worker(
    once: bool = typer.Option(
        False,
        "--once",
        help="Run one snapshot job and exit instead of starting the scheduler.",
    ),
) -> None:
    from collector.worker import run_worker

    _run_async(lambda: run_worker(once=once))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes."),
    with_scheduler: bool = typer.Option(
        False, "--with-scheduler", help="Run the background snapshot scheduler."
    ),
) -> None:
    def _impl() -> None:
        import uvicorn

        from api.app import create_app
        from config import settings, validate_runtime_configuration
        from logging_config import configure_logging

        try:
            validate_runtime_configuration()
        except ConfigurationError as exc:
            _fail(f"unsafe production configuration: {exc}", ExitCode.CONFIG)
        configure_logging(
            level=settings.log_level,
            json_logs=settings.log_format.lower() == "json",
        )
        if with_scheduler:
            settings.scheduler_enabled = True

        uvicorn.run(create_app(), host=host, port=port, reload=reload)

    _impl()


async def _store_repos(repos: list[RepoSummary]) -> int:
    from collector.store import save_repos
    from db.base import SessionFactory

    async with SessionFactory() as session:
        return await save_repos(session, repos)


def _require_full_name(full_name: str) -> str:
    value = full_name.strip()
    if value.count("/") != 1 or any(not part for part in value.split("/")):
        _fail("expected owner/name format, e.g. psf/requests", ExitCode.USAGE)
    return value


TRACKING_COLUMNS: tuple[Column, ...] = (
    Column("repository", "Repository"),
    Column("status", "Status"),
    Column("label", "Label"),
    Column("snapshot_count", "Snapshots", align="right"),
    Column("last_successful_snapshot_at", "Last success (UTC)"),
    Column("last_snapshot_error", "Last error"),
)


def _emit_tracking_rows(
    rows: list[dict[str, object]],
    output: str,
    *,
    title: str,
    empty_message: str,
) -> None:
    emit_rows(
        rows,
        TRACKING_COLUMNS,
        output,
        title=title,
        empty_message=empty_message,
        console=console,
    )


@repos_app.command("add")
def repos_add(
    full_name: str = typer.Argument(..., metavar="owner/name"),
    label: str | None = typer.Option(None, "--label", "-l"),
) -> None:
    full_name = _require_full_name(full_name)

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.repositories import create_snapshot, upsert_repository
        from tracking.service import track

        async with GitHubClient() as client:
            fresh = await client.get_repo(full_name)
        async with SessionFactory() as session:
            repo = await upsert_repository(
                session,
                fresh,
                track=True,
                tracking_label=label.strip() if label else None,
            )
            await track(session, repo, label=label)
            await create_snapshot(
                session,
                repo.id,
                stargazers=fresh.stargazers_count,
                forks=fresh.forks_count,
                open_issues=fresh.open_issues_count,
            )
            await session.commit()
        _info(f"[green]Now tracking {full_name}.[/green]")

    _run_async(_impl)


@repos_app.command("remove")
def repos_remove(full_name: str = typer.Argument(..., metavar="owner/name")) -> None:
    full_name = _require_full_name(full_name)

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name
        from tracking.service import untrack

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                _fail(f"repository not known: {full_name}", ExitCode.ERROR)
            await untrack(session, repo)
            await session.commit()
        _info(f"[green]Stopped tracking {full_name}; history was kept.[/green]")

    _run_async(_impl)


@repos_app.command("pause")
def repos_pause(full_name: str = typer.Argument(..., metavar="owner/name")) -> None:
    full_name = _require_full_name(full_name)

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name
        from tracking.service import pause

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                _fail(f"repository not known: {full_name}", ExitCode.ERROR)
            await pause(session, repo)
            await session.commit()
        _info(f"[yellow]Paused tracking for {full_name}.[/yellow]")

    _run_async(_impl)


@repos_app.command("resume")
def repos_resume(full_name: str = typer.Argument(..., metavar="owner/name")) -> None:
    full_name = _require_full_name(full_name)

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name
        from tracking.service import resume

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                _fail(f"repository not known: {full_name}", ExitCode.ERROR)
            await resume(session, repo)
            await session.commit()
        _info(f"[green]Resumed tracking for {full_name}.[/green]")

    _run_async(_impl)


@repos_app.command("refresh")
def repos_refresh(full_name: str = typer.Argument(..., metavar="owner/name")) -> None:
    full_name = _require_full_name(full_name)

    async def _impl() -> None:
        from collector.pipeline import run_snapshot
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name
        from tracking.service import tracking_state

        async with SessionFactory() as session:
            if await get_repository_by_name(session, full_name) is None:
                _fail(f"repository not known: {full_name}", ExitCode.ERROR)
        saved = await run_snapshot(repo_name=full_name, force=True)
        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            assert repo is not None
            state = await tracking_state(session, repo)
        if state.status.value == "failed":
            _fail(f"refresh failed: {state.last_snapshot_error}", ExitCode.ERROR)
        console.print(
            f"[green]Refresh complete for {full_name} ({saved} snapshot saved).[/green]"
        )

    _run_async(_impl)


@repos_app.command("list")
def repos_list(
    all_repositories: bool = typer.Option(
        False, "--all", help="Include untracked repositories."
    ),
    status: str | None = typer.Option(None, "--status"),
    label: str | None = typer.Option(None, "--label"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """List known repositories with their tracking state."""

    resolved = _resolve_output(output)
    valid_statuses = {"healthy", "stale", "failed", "paused", "untracked"}
    if status is not None and status not in valid_statuses:
        _fail(
            f"unknown tracking status {status!r} "
            f"(choose from {', '.join(sorted(valid_statuses))})",
            ExitCode.USAGE,
        )
    _require_database()

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.repositories import list_repositories
        from tracking.service import tracking_state

        scope = "all" if all_repositories or status == "untracked" else "tracked"
        async with SessionFactory() as session:
            repos, _total = await list_repositories(
                session,
                tracking=scope,
                label=label,
                limit=10000,
                sort="name",
            )
            rows: list[dict[str, object]] = []
            for repo in repos:
                state = await tracking_state(session, repo)
                if status is not None and state.status.value != status:
                    continue
                rows.append(
                    {
                        "id": repo.id,
                        "repository": repo.full_name,
                        "status": state.status.value,
                        "tracking_enabled": state.tracking_enabled,
                        "tracking_paused": state.tracking_paused,
                        "label": state.label,
                        "snapshot_count": state.snapshot_count,
                        "history_start_at": state.history_start_at,
                        "last_successful_snapshot_at": state.last_successful_snapshot_at,
                        "last_snapshot_attempt_at": state.last_snapshot_attempt_at,
                        "last_snapshot_error": state.last_snapshot_error,
                        "next_snapshot_at": state.next_snapshot_at,
                    }
                )
        _emit_tracking_rows(
            rows,
            resolved,
            title="Tracked repositories",
            empty_message="No tracked repositories. Add one with `radar repos add`.",
        )

    _run_async(_impl)


# Table output stays narrow enough for an 80-column terminal; the extra
# machine-readable fields are still present in JSON and CSV.
_REPO_TABLE_COLUMNS: tuple[Column, ...] = (
    Column("rank", "#", align="right"),
    Column("repository", "Repository"),
    Column("language", "Language"),
    Column("stars", "Stars", align="right"),
    Column("forks", "Forks", align="right"),
)
_REPO_CSV_COLUMNS: tuple[Column, ...] = (
    *_REPO_TABLE_COLUMNS,
    Column("html_url", "URL"),
)


def _repo_rows(repos: list[RepoSummary]) -> list[dict[str, object]]:
    return [
        {
            "rank": index,
            "repository": repo.full_name,
            "language": repo.language,
            "stars": repo.stargazers_count,
            "forks": repo.forks_count,
            "html_url": repo.html_url,
        }
        for index, repo in enumerate(repos, start=1)
    ]


def _emit_repo_rows(
    repos: list[RepoSummary],
    output: str,
    *,
    title: str,
    empty_message: str,
) -> None:
    columns = _REPO_TABLE_COLUMNS if output == "table" else _REPO_CSV_COLUMNS
    emit_rows(
        _repo_rows(repos),
        columns,
        output,
        title=title,
        empty_message=empty_message,
        console=console,
    )


@app.command()
def top(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        min=1,
        max=100,
        help="How many repositories to show.",
    ),
    save: bool = typer.Option(False, "--save", help="Store results in the database."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Show the most-starred repositories on GitHub."""

    resolved = _resolve_output(output)
    _warn_missing_token()

    async def _impl() -> None:
        async with GitHubClient() as client:
            repos = await client.search_repos("stars:>1000", per_page=limit)
        if save:
            saved = await _store_repos(repos)
            _info(f"[green]Saved {saved} repositories.[/green]")
        _emit_repo_rows(
            repos,
            resolved,
            title="Top repositories by stars",
            empty_message="No repositories matched the search.",
        )

    _run_async(_impl)


@app.command()
def search(
    query: str = typer.Option("", "--query", "-q", help="Free-text search query."),
    language: str = typer.Option(
        None, "--language", "-l", help="Filter by language, e.g. python."
    ),
    min_stars: int = typer.Option(
        50, "--min-stars", min=0, help="Minimum number of stars."
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        min=1,
        max=100,
        help="How many repositories to show.",
    ),
    save: bool = typer.Option(False, "--save", help="Store results in the database."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Search GitHub repositories and optionally store the results."""

    resolved = _resolve_output(output)
    parts = [
        part
        for part in (
            query.strip(),
            language and f"language:{language}",
            min_stars and f"stars:>={min_stars}",
        )
        if part
    ]
    q = " ".join(parts)
    if not q:
        _fail(
            "give --query or at least one filter (--language/--min-stars)",
            ExitCode.USAGE,
        )
    _warn_missing_token()

    async def _impl() -> None:
        async with GitHubClient() as client:
            repos = await client.search_repos(q, per_page=limit)
        if save:
            saved = await _store_repos(repos)
            _info(f"[green]Saved {saved} repositories.[/green]")
        _emit_repo_rows(
            repos,
            resolved,
            title="Search results",
            empty_message="No repositories matched the query.",
        )

    _run_async(_impl)


@app.command()
def history(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Tracked repository in owner/name format, e.g. psf/requests.",
    ),
    days: int = typer.Option(30, "--days", min=1, help="How many days back to show."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Show stored snapshots for a tracked repository."""

    resolved = _resolve_output(output)
    full_name = _require_full_name(full_name)
    _require_database()

    async def _impl() -> None:
        from datetime import datetime, timedelta

        from db.base import SessionFactory
        from db.repositories import get_history, get_repository_by_name

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                _fail(f"repository not tracked: {full_name}")
            since = datetime.now(UTC) - timedelta(days=days)
            assert repo is not None
            snapshots = await get_history(session, repo.id, since=since)

        rows: list[dict[str, object]] = []
        previous: int | None = None
        for snap in snapshots:
            delta = snap.stargazers_count - previous if previous is not None else 0
            rows.append(
                {
                    "observed_at": snap.observed_at,
                    "stars": snap.stargazers_count,
                    "forks": snap.forks_count,
                    "open_issues": snap.open_issues_count,
                    "stars_delta": delta,
                    "quality_status": snap.quality_status,
                }
            )
            previous = snap.stargazers_count

        emit_rows(
            rows,
            (
                Column("observed_at", "Observed at (UTC)"),
                Column("stars", "Stars", align="right"),
                Column("forks", "Forks", align="right"),
                Column("open_issues", "Open issues", align="right"),
                Column("stars_delta", "Δ stars", align="right"),
                Column("quality_status", "Quality"),
            ),
            resolved,
            title=f"History: {full_name} (last {days} days)",
            empty_message=f"No snapshots for {full_name} in the last {days} days.",
            console=console,
        )

    _run_async(_impl)


@app.command()
def snapshot(
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table or json."
    ),
) -> None:
    """Collect one snapshot for every active tracked repository."""

    resolved = _resolve_output(output)
    _require_database()
    _warn_missing_token()

    async def _impl() -> None:
        from collector.pipeline import run_snapshot_result

        result = await run_snapshot_result()
        payload = {
            "saved": result.saved,
            "total_repositories": result.total_repositories,
            "succeeded_repositories": result.succeeded_repositories,
            "failed_repositories": result.failed_repositories,
            "skipped_repositories": result.skipped_repositories,
        }
        if resolved == "json":
            emit_document(payload, "json")
        elif result.saved:
            _info(
                f"[green]Snapshot complete: {result.saved} repository(-ies) updated.[/green]"
            )
        else:
            _info(
                "[yellow]No tracked repositories yet. Try `radar top --save` first.[/yellow]"
            )
        if result.failed_repositories:
            raise typer.Exit(ExitCode.ERROR)

    _run_async(_impl)


@app.command()
def backfill(
    full_name: str | None = typer.Argument(None, metavar="owner/name"),
    all_repositories: bool = typer.Option(
        False, "--all", help="Backfill every active tracked repository."
    ),
    days: int = typer.Option(30, "--days", min=1, max=3650),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Plan work without writing snapshots."
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=0, help="Maximum missing days per repository."
    ),
    max_pages: int | None = typer.Option(
        None, "--max-pages", min=1, help="Maximum GitHub stargazer pages."
    ),
    concurrency: int = typer.Option(
        1,
        "--concurrency",
        min=1,
        help="Maximum concurrent repositories (safe default: 1).",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Import GitHub stargazer history into the snapshot store."""

    resolved = _resolve_output(output)
    if (full_name is None) == (not all_repositories):
        _fail("give owner/name or use --all", ExitCode.USAGE)
    if full_name is not None:
        full_name = _require_full_name(full_name)
    _require_database()
    _warn_missing_token()

    async def _impl() -> None:
        from collector.backfill import run_backfill
        from config import settings
        from db.base import SessionFactory

        async with SessionFactory() as session:
            result = await run_backfill(
                [full_name] if full_name else None,
                days=days,
                dry_run=dry_run,
                limit=limit,
                max_pages=(
                    max_pages if max_pages is not None else settings.backfill_max_pages
                ),
                concurrency=concurrency,
                session=session,
            )
        title = "Backfill plan" if dry_run else "Backfill result"
        rows = [
            {
                "repository": item.repository,
                "status": (
                    "planned"
                    if dry_run
                    else ("failed" if item.error else "updated")
                ),
                "planned": item.planned,
                "inserted": item.inserted,
                "skipped_existing": item.skipped_existing,
                "error": item.error,
            }
            for item in result.repositories
        ]
        emit_rows(
            rows,
            (
                Column("repository", "Repository"),
                Column("status", "Status"),
                Column("planned", "Planned", align="right"),
                Column("inserted", "Inserted", align="right"),
                Column("skipped_existing", "Existing", align="right"),
                Column("error", "Error"),
            ),
            resolved,
            title=title,
            empty_message="No active tracked repositories found.",
            console=console,
        )
        action = "Planned" if dry_run else "Inserted"
        count = result.planned if dry_run else result.inserted
        if resolved == "table":
            _info(f"[green]{action} {count} snapshot(s).[/green]")
        if any(item.error for item in result.repositories):
            raise typer.Exit(ExitCode.ERROR)

    _run_async(_impl)


@app.command("quota")
def quota(
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Show the current GitHub API rate limit."""

    resolved = _resolve_output(output)
    _warn_missing_token()

    async def _impl() -> None:
        from datetime import datetime

        async with GitHubClient() as client:
            data = await client.get_rate_limit()
        reset = int(data.get("reset") or 0)
        row = {
            "resource": str(data["resource"]),
            "limit": int(data["limit"]),
            "used": int(data["used"]),
            "remaining": int(data["remaining"]),
            "reset_at": (
                datetime.fromtimestamp(reset, UTC) if reset else None
            ),
        }
        emit_rows(
            [row],
            (
                Column("resource", "Resource"),
                Column("limit", "Limit", align="right"),
                Column("used", "Used", align="right"),
                Column("remaining", "Remaining", align="right"),
                Column("reset_at", "Resets at (UTC)"),
            ),
            resolved,
            title="GitHub API rate limit",
            console=console,
        )

    _run_async(_impl)


@app.command()
def repo(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Repository in owner/name format, e.g. psf/requests",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table or json."
    ),
) -> None:
    """Show live GitHub metadata for one repository."""

    resolved = _resolve_output(output)
    full_name = _require_full_name(full_name)
    _warn_missing_token()

    async def _impl() -> None:
        async with GitHubClient() as client:
            result = await client.get_repo(full_name)
        if resolved == "json":
            emit_document(result.model_dump(), "json")
            return
        if resolved == "csv":
            _fail("`radar repo` supports table or json output only", ExitCode.USAGE)
        panel = Panel(
            f"[bold]{result.full_name}[/bold]\n\n{result.description or '—'}\n\n"
            f"Language: {result.language or '—'}\n"
            f"Stars: {result.stargazers_count:,}\n"
            f"Forks: {result.forks_count:,}\n"
            f"URL: {result.html_url}",
            title="Repository",
        )
        console.print(panel)

    _run_async(_impl)


@app.command()
def velocity(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Tracked repository in owner/name format, e.g. psf/requests.",
    ),
    history_days: int = typer.Option(
        180, "--history-days", min=7, help="How many days of history to use."
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Show star velocity over the standard windows."""

    resolved = _resolve_output(output)
    full_name = _require_full_name(full_name)
    _require_database()

    async def _impl() -> None:
        from analytics import service
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                _fail(f"repository not tracked: {full_name}")
            assert repo is not None
            velocities, trend, _stars = await service.repo_velocity(
                session, repo.id, windows=(7, 30, 90), history_days=history_days
            )

        rows = [
            {
                "repository": full_name,
                "window_days": v.window_days,
                "stars_per_day": round(v.stars_per_day, 4),
                "stars_gained": v.stars_gained,
                "start_day": v.start_day,
                "end_day": v.end_day,
            }
            for v in velocities
        ]
        if resolved == "json":
            emit_document(
                {
                    "repository": full_name,
                    "history_days": history_days,
                    "velocities": rows,
                    "trend": to_jsonable(trend),
                },
                "json",
            )
            return
        emit_rows(
            rows,
            (
                Column("repository", "Repository"),
                Column("window_days", "Window (days)", align="right"),
                Column("stars_per_day", "Stars/day", align="right"),
                Column("stars_gained", "Gained", align="right"),
                Column("start_day", "Start"),
                Column("end_day", "End"),
            ),
            resolved,
            title=f"Velocity: {full_name}",
            empty_message=f"Not enough snapshot history for {full_name}.",
            console=console,
        )
        if resolved == "table" and trend is not None:
            console.print(
                f"OLS trend: [bold]{trend.slope:.2f}[/bold] stars/day, "
                f"R² {trend.r_squared:.3f} ({trend.n_points} points)"
            )

    _run_async(_impl)


@app.command()
def bursts(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Tracked repository in owner/name format, e.g. psf/requests.",
    ),
    days: int = typer.Option(90, "--days", min=7, help="How many days back to scan."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Detect growth bursts for a tracked repository."""

    resolved = _resolve_output(output)
    full_name = _require_full_name(full_name)
    _require_database()

    async def _impl() -> None:
        from analytics import service
        from config import settings
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                _fail(f"repository not tracked: {full_name}")
            assert repo is not None
            events, active = await service.repo_bursts(
                session,
                repo.id,
                history_days=days,
                rolling_window=settings.analytics_rolling_window,
                z_threshold=settings.analytics_burst_z,
                min_delta=settings.analytics_burst_min_delta,
                min_duration=settings.analytics_burst_min_days,
            )

        rows = [to_jsonable(event) for event in events]
        if resolved == "json":
            emit_document(
                {
                    "repository": full_name,
                    "days": days,
                    "active_burst": active,
                    "items": rows,
                },
                "json",
            )
            return
        emit_rows(
            rows,
            (
                Column("start_day", "Start"),
                Column("end_day", "End"),
                Column("duration_days", "Days", align="right"),
                Column("peak_day", "Peak day"),
                Column("peak_delta", "Peak Δ", align="right"),
                Column("total_gained", "Gained", align="right"),
                Column("severity", "Severity", align="right"),
            ),
            resolved,
            title=f"Bursts: {full_name} (last {days} days)",
            empty_message=f"No bursts detected for {full_name} in the last {days} days.",
            console=console,
        )
        if resolved == "table" and active:
            console.print(
                "[red bold]ACTIVE BURST[/red bold] — the repo is taking off right now."
            )

    _run_async(_impl)


@app.command()
def leaderboard(
    window: int = typer.Option(
        7, "--window", "-w", min=7, max=90, help="Time window in days: 7, 30 or 90."
    ),
    limit: int = typer.Option(
        20, "--limit", "-n", min=1, max=100, help="How many repositories to show."
    ),
    language: str | None = typer.Option(None, "--language", "-l"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Rank tracked repositories by star growth."""

    resolved = _resolve_output(output)
    if window not in (7, 30, 90):
        _fail("--window must be 7, 30 or 90", ExitCode.USAGE)
    _require_database()

    async def _impl() -> None:
        from analytics import service
        from db.base import SessionFactory

        async with SessionFactory() as session:
            _total, scored = await service.leaderboard(
                session,
                window_days=window,
                limit=limit,
                offset=0,
                language=language,
            )

        rows: list[dict[str, object]] = []
        for index, (repo, velocity, stars) in enumerate(scored, start=1):
            owner, _, name = repo.full_name.partition("/")
            rows.append(
                {
                    "rank": index,
                    "owner": owner,
                    "name": name,
                    "full_name": repo.full_name,
                    "language": repo.language,
                    "stars": stars,
                    "stars_per_day": round(velocity.stars_per_day, 2),
                    "stars_gained": velocity.stars_gained,
                }
            )
        emit_rows(
            rows,
            (
                Column("rank", "#", align="right"),
                Column("full_name", "Repository"),
                Column("language", "Language"),
                Column("stars", "Stars", align="right"),
                Column("stars_per_day", "Per day", align="right"),
                Column("stars_gained", "Gained", align="right"),
            ),
            resolved,
            title=f"Fastest growing ({window}d window)",
            empty_message="No tracked repositories with enough snapshot history.",
            console=console,
        )

    _run_async(_impl)


_ALERT_TYPE_ALIASES = {
    "burst": "burst_started",
    "velocity": "velocity_above",
    "milestone": "stars_reached",
}


@app.command("export")
def export_analytics(
    target: str = typer.Argument(..., metavar="owner/name|leaderboard"),
    format: str = typer.Option("json", "--format", help="json or csv"),
    window: int = typer.Option(7, "--window", min=7, max=90),
    output_file: str | None = typer.Option(
        None, "--output", help="Write to a file instead of stdout."
    ),
) -> None:
    if format not in {"json", "csv"}:
        _fail("--format must be json or csv", ExitCode.USAGE)
    if target != "leaderboard":
        target = _require_full_name(target)
    if target == "leaderboard" and window not in {7, 30, 90}:
        _fail("--window must be one of 7, 30 or 90", ExitCode.USAGE)
    _require_database()

    async def _impl() -> None:
        from analytics import service
        from analytics.export import leaderboard_csv, repository_payload, series_csv
        from config import settings
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name
        from tracking.service import tracking_state

        if target == "leaderboard":
            async with SessionFactory() as session:
                _total, scored = await service.leaderboard(
                    session, window_days=window, limit=100, offset=0
                )
            rows = []
            for index, (repo, velocity, stars) in enumerate(scored, start=1):
                owner, _, name = repo.full_name.partition("/")
                rows.append(
                    {
                        "rank": index,
                        "owner": owner,
                        "name": name,
                        "full_name": repo.full_name,
                        "language": repo.language,
                        "stars": stars,
                        "stars_per_day": velocity.stars_per_day,
                        "stars_gained": velocity.stars_gained,
                    }
                )
            content = (
                leaderboard_csv(rows)
                if format == "csv"
                else json.dumps(
                    {"format_version": "0.8", "window_days": window, "items": rows},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            async with SessionFactory() as session:
                repo = await get_repository_by_name(session, target)
                if repo is None:
                    _fail(f"repository not known: {target}", ExitCode.ERROR)
                series = await service.repo_series(
                    session, repo.id, history_days=max(window, 7)
                )
                velocities, trend, _stars = await service.repo_velocity(
                    session,
                    repo.id,
                    windows=(7, 30, 90),
                    history_days=max(window, 7),
                )
                bursts, _active = await service.repo_bursts(
                    session,
                    repo.id,
                    history_days=max(window, 7),
                    rolling_window=settings.analytics_rolling_window,
                    z_threshold=settings.analytics_burst_z,
                    min_delta=settings.analytics_burst_min_delta,
                    min_duration=settings.analytics_burst_min_days,
                )
                state = await tracking_state(session, repo)
            if format == "csv":
                content = series_csv(series)
            else:
                state_payload = {
                    "status": state.status.value,
                    "tracking_enabled": state.tracking_enabled,
                    "tracking_paused": state.tracking_paused,
                    "label": state.label,
                    "snapshot_count": state.snapshot_count,
                    "history_start_at": (
                        state.history_start_at.isoformat()
                        if state.history_start_at
                        else None
                    ),
                    "last_successful_snapshot_at": (
                        state.last_successful_snapshot_at.isoformat()
                        if state.last_successful_snapshot_at
                        else None
                    ),
                    "last_snapshot_attempt_at": (
                        state.last_snapshot_attempt_at.isoformat()
                        if state.last_snapshot_attempt_at
                        else None
                    ),
                    "last_snapshot_error": state.last_snapshot_error,
                }
                content = json.dumps(
                    repository_payload(
                        full_name=target,
                        series=series,
                        velocities=velocities,
                        trend=trend,
                        bursts=bursts,
                        tracking=state_payload,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
        if output_file:
            from pathlib import Path

            Path(output_file).write_text(
                content + ("" if content.endswith("\n") else "\n")
            )
            _info(f"[green]Export written to {output_file}.[/green]")
        else:
            typer.echo(content, nl=not content.endswith("\n"))

    _run_async(_impl)


@alerts_app.command("add")
def alerts_add(
    full_name: str = typer.Argument(..., metavar="owner/name"),
    alert_type: str = typer.Option(..., "--type", help="burst, velocity or milestone"),
    threshold: float | None = typer.Option(None, "--threshold"),
    window: int | None = typer.Option(None, "--window"),
    disabled: bool = typer.Option(
        False, "--disabled", help="Create the rule disabled."
    ),
) -> None:
    kind = _ALERT_TYPE_ALIASES.get(alert_type)
    if kind is None:
        _fail("--type must be burst, velocity or milestone", ExitCode.USAGE)

    async def _impl() -> None:
        from alerts import RuleSpec, validate_rule
        from db.alerts import create_rule
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name

        try:
            spec = validate_rule(
                RuleSpec(kind=kind, threshold=threshold, window_days=window)
            )
        except ValueError as exc:
            _fail(str(exc), ExitCode.USAGE)

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                _fail(f"repository not tracked: {full_name}", ExitCode.ERROR)
            rule = await create_rule(session, repo, spec, enabled=not disabled)
            await session.commit()
        _info(f"[green]Created alert rule #{rule.id}[/green] for {full_name}.")

    _run_async(_impl)


def _rule_condition(rule) -> str:
    if rule.kind == "velocity_above":
        return f">= {rule.threshold:g}/day ({rule.window_days}d)"
    if rule.kind == "stars_reached":
        return f">= {rule.threshold:g} stars"
    return "new burst"


@alerts_app.command("list")
def alerts_list(
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """List configured alert rules."""

    resolved = _resolve_output(output)
    _require_database()

    async def _impl() -> None:
        from db.alerts import list_rules
        from db.base import SessionFactory

        async with SessionFactory() as session:
            rules, _total = await list_rules(session)
        rows = [
            {
                "id": rule.id,
                "repository": rule.repository.full_name,
                "kind": rule.kind,
                "condition": _rule_condition(rule),
                "threshold": rule.threshold,
                "window_days": rule.window_days,
                "enabled": rule.enabled,
                "last_value": rule.last_value,
                "last_evaluated_at": rule.last_evaluated_at,
            }
            for rule in rules
        ]
        emit_rows(
            rows,
            (
                Column("id", "ID", align="right"),
                Column("repository", "Repository"),
                Column("kind", "Type"),
                Column("condition", "Condition"),
                Column("enabled", "Enabled"),
                Column("last_value", "Last value", align="right"),
            ),
            resolved,
            title="Alert rules",
            empty_message="No alert rules configured.",
            console=console,
        )

    _run_async(_impl)


async def _set_alert_rule_enabled(rule_id: int, enabled: bool) -> None:
    from db.alerts import get_rule
    from db.base import SessionFactory

    async with SessionFactory() as session:
        rule = await get_rule(session, rule_id)
        if rule is None:
            _fail(f"alert rule not found: {rule_id}", ExitCode.ERROR)
        rule.enabled = enabled
        await session.commit()
    state = "enabled" if enabled else "disabled"
    _info(f"[green]Alert rule #{rule_id} {state}.[/green]")


@alerts_app.command("enable")
def alerts_enable(rule_id: int = typer.Argument(..., min=1)) -> None:
    _run_async(lambda: _set_alert_rule_enabled(rule_id, True))


@alerts_app.command("disable")
def alerts_disable(rule_id: int = typer.Argument(..., min=1)) -> None:
    _run_async(lambda: _set_alert_rule_enabled(rule_id, False))


@alerts_app.command("delete")
def alerts_delete(
    rule_id: int = typer.Argument(..., min=1),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if not yes and not _confirm(f"Delete alert rule #{rule_id}?"):
        _abort()

    async def _impl() -> None:
        from db.alerts import delete_rule, get_rule
        from db.base import SessionFactory

        async with SessionFactory() as session:
            rule = await get_rule(session, rule_id)
            if rule is None:
                _fail(f"alert rule not found: {rule_id}", ExitCode.ERROR)
            await delete_rule(session, rule)
            await session.commit()
        _info(f"[green]Deleted alert rule #{rule_id}.[/green]")

    _run_async(_impl)


@alerts_app.command("events")
def alerts_events(
    unread: bool = typer.Option(False, "--unread", help="Show only unread events."),
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=100),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Show the alert inbox."""

    resolved = _resolve_output(output)
    _require_database()

    async def _impl() -> None:
        from db.alerts import list_events
        from db.base import SessionFactory

        async with SessionFactory() as session:
            events, _total = await list_events(
                session,
                acknowledged=False if unread else None,
                limit=limit,
            )
        rows = [
            {
                "id": event.id,
                "created_at": event.created_at,
                "repository": event.repository_full_name,
                "kind": event.kind,
                "title": event.title,
                "message": event.message,
                "current_value": event.current_value,
                "delivery_status": event.delivery_status,
                "acknowledged": event.acknowledged_at is not None,
            }
            for event in events
        ]
        emit_rows(
            rows,
            (
                Column("id", "ID", align="right"),
                Column("created_at", "Created (UTC)"),
                Column("repository", "Repository"),
                Column("kind", "Type"),
                Column("acknowledged", "Read"),
                Column("message", "Message"),
            ),
            resolved,
            title="Alert events",
            empty_message="No alert events found.",
            console=console,
        )

    _run_async(_impl)


@alerts_app.command("acknowledge")
def alerts_acknowledge(event_id: int = typer.Argument(..., min=1)) -> None:
    async def _impl() -> None:
        from db.alerts import get_event, set_event_acknowledged
        from db.base import SessionFactory

        async with SessionFactory() as session:
            event = await get_event(session, event_id)
            if event is None:
                _fail(f"alert event not found: {event_id}", ExitCode.ERROR)
            await set_event_acknowledged(session, event, True)
            await session.commit()
        _info(f"[green]Acknowledged alert event #{event_id}.[/green]")

    _run_async(_impl)


@alerts_app.command("acknowledge-all")
def alerts_acknowledge_all(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if not yes and not _confirm("Acknowledge all unread alert events?"):
        _abort()

    async def _impl() -> None:
        from db.alerts import acknowledge_all_events
        from db.base import SessionFactory

        async with SessionFactory() as session:
            changed = await acknowledge_all_events(session)
            await session.commit()
        _info(f"[green]Acknowledged {changed} alert event(s).[/green]")

    _run_async(_impl)


@notifications_app.command("add")
def notifications_add(
    name: str = typer.Argument(..., help="Stable endpoint name."),
    url: str = typer.Argument(..., help="HTTPS webhook URL."),
    provider: str = typer.Option(
        "generic", "--provider", help="generic, slack or discord"
    ),
    signing_secret: str | None = typer.Option(
        None,
        "--signing-secret",
        envvar="RADAR_WEBHOOK_SIGNING_SECRET",
        help="HMAC secret; prefer the environment variable for shell history safety.",
    ),
) -> None:
    if provider not in {"generic", "slack", "discord"}:
        _fail("provider must be generic, slack or discord", ExitCode.USAGE)
    from security import UnsafeURL, validate_webhook_url

    try:
        url = validate_webhook_url(url)
    except UnsafeURL as exc:
        _fail(str(exc), ExitCode.USAGE)

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.notifications import create_endpoint, get_endpoint_by_name

        async with SessionFactory() as session:
            if await get_endpoint_by_name(session, name) is not None:
                _fail(f"endpoint already exists: {name}", ExitCode.ERROR)
            endpoint = await create_endpoint(
                session,
                name=name,
                provider=provider,
                url=url,
                signing_secret=signing_secret,
            )
            await session.commit()
        console.print(
            f"[green]Created notification endpoint #{endpoint.id}: {name}.[/green]"
        )

    _run_async(_impl)


@notifications_app.command("list")
def notifications_list(
    enabled: bool | None = typer.Option(None, "--enabled/--disabled"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """List configured webhook notification endpoints."""

    resolved = _resolve_output(output)
    _require_database()

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.notifications import list_endpoints

        async with SessionFactory() as session:
            endpoints, _total = await list_endpoints(session, enabled=enabled)
        rows = [
            {
                "id": endpoint.id,
                "name": endpoint.name,
                "provider": endpoint.provider,
                "enabled": endpoint.enabled,
                "failure_count": endpoint.failure_count,
                "url_configured": bool(endpoint.url),
                "last_delivery_at": endpoint.last_delivery_at,
                "last_error": endpoint.last_error,
            }
            for endpoint in endpoints
        ]
        emit_rows(
            rows,
            (
                Column("id", "ID", align="right"),
                Column("name", "Name"),
                Column("provider", "Provider"),
                Column("enabled", "Enabled"),
                Column("failure_count", "Failures", align="right"),
                Column("last_error", "Last error"),
            ),
            resolved,
            title="Notification endpoints",
            empty_message="No notification endpoints configured.",
            console=console,
        )

    _run_async(_impl)


async def _set_notification_enabled(endpoint_id: int, enabled: bool) -> None:
    from db.base import SessionFactory
    from db.notifications import get_endpoint, set_endpoint_enabled

    async with SessionFactory() as session:
        endpoint = await get_endpoint(session, endpoint_id)
        if endpoint is None:
            _fail(f"notification endpoint not found: {endpoint_id}", ExitCode.ERROR)
        await set_endpoint_enabled(session, endpoint, enabled)
        await session.commit()
    state = "enabled" if enabled else "disabled"
    _info(f"[green]Notification endpoint #{endpoint_id} {state}.[/green]")


@notifications_app.command("enable")
def notifications_enable(endpoint_id: int = typer.Argument(..., min=1)) -> None:
    _run_async(lambda: _set_notification_enabled(endpoint_id, True))


@notifications_app.command("disable")
def notifications_disable(endpoint_id: int = typer.Argument(..., min=1)) -> None:
    _run_async(lambda: _set_notification_enabled(endpoint_id, False))


@notifications_app.command("test")
def notifications_test(endpoint_id: int = typer.Argument(..., min=1)) -> None:
    async def _impl() -> None:
        from alerts.webhook import deliver_test_endpoint
        from config import settings
        from db.base import SessionFactory
        from db.notifications import get_endpoint

        async with SessionFactory() as session:
            endpoint = await get_endpoint(session, endpoint_id)
            if endpoint is None:
                console.print(
                    f"[red]Notification endpoint not found:[/red] {endpoint_id}"
                )
                raise typer.Exit(1)
            sent, error = await deliver_test_endpoint(
                endpoint,
                timeout_seconds=settings.alert_webhook_timeout_seconds,
                max_attempts=settings.webhook_max_attempts,
                backoff_base_seconds=settings.webhook_backoff_base_seconds,
                signing_secret=endpoint.signing_secret
                or settings.webhook_signing_secret,
            )
            endpoint.last_error = error
            await session.commit()
        if not sent:
            _fail(f"webhook test failed: {error}", ExitCode.ERROR)
        _info("[green]Webhook test delivered.[/green]")

    _run_async(_impl)


@notifications_app.command("deliveries")
def notifications_deliveries(
    endpoint_id: int | None = typer.Option(None, "--endpoint-id", min=1),
    delivery_status: str | None = typer.Option(None, "--status"),
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=100),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output format: table, json or csv."
    ),
) -> None:
    """Show webhook delivery attempts."""

    resolved = _resolve_output(output)
    _require_database()

    async def _impl() -> None:
        from db.base import SessionFactory
        from db.notifications import list_deliveries

        async with SessionFactory() as session:
            deliveries, _total = await list_deliveries(
                session,
                endpoint_id=endpoint_id,
                status=delivery_status,
                limit=limit,
            )
        rows = [
            {
                "id": delivery.id,
                "event_id": delivery.event_id,
                "endpoint_id": delivery.endpoint_id,
                "attempt": delivery.attempt,
                "status": delivery.status,
                "response_status": delivery.response_status,
                "attempted_at": delivery.attempted_at,
                "delivered_at": delivery.delivered_at,
                "error": delivery.error,
            }
            for delivery in deliveries
        ]
        emit_rows(
            rows,
            (
                Column("id", "ID", align="right"),
                Column("event_id", "Event", align="right"),
                Column("attempt", "Attempt", align="right"),
                Column("status", "Status"),
                Column("response_status", "HTTP", align="right"),
                Column("error", "Error"),
            ),
            resolved,
            title="Webhook deliveries",
            empty_message="No webhook deliveries found.",
            console=console,
        )

    _run_async(_impl)
