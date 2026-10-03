from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from exit_codes import DatabaseUnavailableError, UsageError

REQUIRED_TABLES: tuple[str, ...] = (
    "repositories",
    "repo_snapshots",
    "alert_rules",
    "alert_events",
    "alert_deliveries",
    "notification_endpoints",
    "snapshot_jobs",
    "job_locks",
    "alembic_version",
)

DEFAULT_BACKUP_PREFIX = "radar-backup"


@dataclass(frozen=True)
class DatabaseState:
    url: str
    backend: str
    location: str | None
    exists: bool
    schema_present: bool
    revision: str | None = None
    head_revision: str | None = None
    size_bytes: int | None = None
    repository_count: int | None = None
    snapshot_count: int | None = None
    alert_event_count: int | None = None
    readonly: bool = False
    detail: str | None = None

    @property
    def migrations_current(self) -> bool:
        return (
            self.schema_present
            and self.revision is not None
            and self.revision == self.head_revision
        )

    @property
    def writable(self) -> bool:
        return self.exists and not self.readonly


@dataclass(frozen=True)
class BackupResult:
    source: str
    destination: str
    size_bytes: int
    revision: str | None
    repository_count: int
    snapshot_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class RestoreResult:
    source: str
    destination: str
    replaced_existing: bool
    safety_backup: str | None
    revision: str | None
    repository_count: int
    snapshot_count: int


@dataclass(frozen=True)
class PruneResult:
    keep_days: int
    keep_min_per_repo: int
    dry_run: bool
    deleted_snapshots: int
    affected_repositories: int
    oldest_kept_at: datetime | None
    cutoff: datetime


def database_path(url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        raw = url[len(prefix) :]
    elif url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
    else:
        return None
    if not raw or raw == ":memory:" or raw.startswith("file::memory:"):
        return None
    return Path(raw).expanduser()


def alembic_script_directory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    for candidate in (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    ):
        if candidate.is_file():
            return ScriptDirectory.from_config(Config(str(candidate)))
    raise DatabaseUnavailableError(
        "alembic.ini not found. Run the command from the project root."
    )


def head_revision() -> str | None:
    try:
        return alembic_script_directory().get_current_head()
    except Exception:  # pragma: no cover - defensive, alembic is a hard dependency
        return None


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row["name"] for row in rows}


def _count(connection: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return None


def _revision(connection: sqlite3.Connection) -> str | None:
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


def database_state(url: str | None = None) -> DatabaseState:
    from config import settings

    active_url = url or settings.database_url
    backend = active_url.split(":", 1)[0]
    path = database_path(active_url)

    if path is None:
        if not active_url.startswith("sqlite"):
            return DatabaseState(
                url=active_url,
                backend=backend,
                location=None,
                exists=True,
                schema_present=True,
                head_revision=head_revision(),
                detail="backup/restore and pruning are only supported for SQLite",
            )
        return DatabaseState(
            url=active_url,
            backend=backend,
            location=None,
            exists=True,
            schema_present=True,
            head_revision=head_revision(),
            detail="in-memory database: nothing is persisted",
        )

    location = str(path)
    if not path.is_file():
        return DatabaseState(
            url=active_url,
            backend=backend,
            location=location,
            exists=False,
            schema_present=False,
            head_revision=head_revision(),
        )

    try:
        connection = _connect(path, readonly=True)
    except sqlite3.Error as exc:
        return DatabaseState(
            url=active_url,
            backend=backend,
            location=location,
            exists=True,
            schema_present=False,
            head_revision=head_revision(),
            detail=f"cannot open database: {exc}",
        )
    with connection:
        tables = _table_names(connection)
        schema_present = "repositories" in tables
        missing = sorted(set(REQUIRED_TABLES) - tables)
        return DatabaseState(
            url=active_url,
            backend=backend,
            location=location,
            exists=True,
            schema_present=schema_present,
            revision=_revision(connection) if "alembic_version" in tables else None,
            head_revision=head_revision(),
            size_bytes=path.stat().st_size,
            repository_count=_count(connection, "repositories"),
            snapshot_count=_count(connection, "repo_snapshots"),
            alert_event_count=_count(connection, "alert_events"),
            detail=(None if not missing else f"missing tables: {', '.join(missing)}"),
        )


def require_database() -> DatabaseState:
    state = database_state()
    if not state.exists:
        raise DatabaseUnavailableError(
            f"database not found at {state.location}. "
            "Run `radar init-db` for a new install or `radar migrate` to upgrade one."
        )
    if not state.schema_present:
        raise DatabaseUnavailableError(
            f"database at {state.location} has no schema"
            + (f" ({state.detail})" if state.detail else "")
            + ". Run `radar init-db` or `radar migrate`."
        )
    return state


def _validate_sqlite_file(
    path: Path,
    *,
    expected_tables: tuple[str, ...] = ("repositories",),
) -> None:
    if not path.is_file():
        raise UsageError(f"file not found: {path}")
    try:
        connection = _connect(path, readonly=True)
    except sqlite3.Error as exc:
        raise UsageError(f"not a readable SQLite database: {path} ({exc})") from exc
    with connection:
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = _table_names(connection)
        except sqlite3.DatabaseError as exc:
            raise UsageError(f"not a readable SQLite database: {path} ({exc})") from exc
        if str(integrity).lower() != "ok":
            raise UsageError(f"integrity check failed for {path}: {integrity}")
        missing = [table for table in expected_tables if table not in tables]
        if missing:
            raise UsageError(
                f"{path} is not a GitHub Radar database (missing: {', '.join(missing)})"
            )


def _default_backup_name() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{DEFAULT_BACKUP_PREFIX}-{stamp}.db"


def backup_database(destination: str | Path | None = None) -> BackupResult:
    state = require_database()
    if state.location is None:
        raise UsageError("backup is only supported for file-based SQLite databases")
    source = Path(state.location)

    target = (
        Path(destination) if destination is not None else Path(_default_backup_name())
    )
    if target.is_dir():
        target = target / _default_backup_name()
    if target.resolve() == source.resolve():
        raise UsageError("backup destination must differ from the source database")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise UsageError(
            f"backup destination already exists: {target} (choose another path)"
        )

    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        source_connection = _connect(source, readonly=True)
        with source_connection:
            destination_connection = sqlite3.connect(temporary)
            try:
                source_connection.backup(destination_connection)
            finally:
                destination_connection.close()
        _validate_sqlite_file(temporary, expected_tables=REQUIRED_TABLES)
        os.replace(temporary, target)
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(f"backup failed: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)

    with _connect(target, readonly=True) as connection:
        revision = _revision(connection)
        repositories = _count(connection, "repositories") or 0
        snapshots = _count(connection, "repo_snapshots") or 0
    return BackupResult(
        source=str(source),
        destination=str(target),
        size_bytes=target.stat().st_size,
        revision=revision,
        repository_count=repositories,
        snapshot_count=snapshots,
    )


def restore_database(
    source: str | Path,
    destination: str | Path | None = None,
    *,
    force: bool = False,
    safety_backup: bool = True,
) -> RestoreResult:
    state = database_state()
    if state.location is None:
        raise UsageError("restore is only supported for file-based SQLite databases")
    source_path = Path(source).expanduser()
    _validate_sqlite_file(source_path, expected_tables=REQUIRED_TABLES)

    target = (
        Path(destination).expanduser()
        if destination is not None
        else Path(state.location)
    )
    if target.resolve() == source_path.resolve():
        raise UsageError("restore source and destination are the same file")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        raise UsageError(
            f"destination already exists: {target} (pass --force to replace it)"
        )

    safety_path: Path | None = None
    if target.exists() and safety_backup:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        safety_path = target.with_name(f"{target.name}.pre-restore-{stamp}.bak")
        shutil.copy2(target, safety_path)

    temporary = target.with_name(f".{target.name}.restore-{os.getpid()}")
    try:
        shutil.copy2(source_path, temporary)
        _validate_sqlite_file(temporary, expected_tables=REQUIRED_TABLES)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

    with _connect(target, readonly=True) as connection:
        revision = _revision(connection)
        repositories = _count(connection, "repositories") or 0
        snapshots = _count(connection, "repo_snapshots") or 0
    return RestoreResult(
        source=str(source_path),
        destination=str(target),
        replaced_existing=target.exists(),
        safety_backup=str(safety_path) if safety_path else None,
        revision=revision,
        repository_count=repositories,
        snapshot_count=snapshots,
    )


def prune_snapshots(
    keep_days: int,
    *,
    keep_min_per_repo: int = 1,
    dry_run: bool = False,
    now: datetime | None = None,
) -> PruneResult:
    if keep_days < 1:
        raise UsageError("--keep-days must be at least 1")
    if keep_min_per_repo < 0:
        raise UsageError("--keep-min-per-repo must not be negative")

    state = require_database()
    if state.location is None:
        raise UsageError("prune is only supported for file-based SQLite databases")

    cutoff = (now or datetime.now(UTC)) - timedelta(days=keep_days)
    cutoff_text = cutoff.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")

    with sqlite3.connect(state.location) as connection:
        candidates = connection.execute(
            """
            SELECT id, repo_id, observed_at FROM repo_snapshots
            WHERE observed_at < ?
              AND id NOT IN (
                SELECT id FROM (
                  SELECT id,
                         ROW_NUMBER() OVER (
                           PARTITION BY repo_id ORDER BY observed_at DESC, id DESC
                         ) AS rn
                  FROM repo_snapshots
                ) WHERE rn <= ?
              )
            """,
            (cutoff_text, keep_min_per_repo),
        ).fetchall()
        affected = len({row[1] for row in candidates})
        deleted = 0
        if candidates and not dry_run:
            connection.executemany(
                "DELETE FROM repo_snapshots WHERE id = ?",
                [(row[0],) for row in candidates],
            )
            connection.commit()
            deleted = len(candidates)

        oldest_kept = connection.execute(
            "SELECT MIN(observed_at) FROM repo_snapshots"
        ).fetchone()[0]
        if not dry_run:
            connection.execute("PRAGMA optimize")

    oldest_dt: datetime | None = None
    if oldest_kept:
        try:
            oldest_dt = datetime.fromisoformat(str(oldest_kept)).replace(tzinfo=UTC)
        except ValueError:  # pragma: no cover - defensive
            oldest_dt = None

    return PruneResult(
        keep_days=keep_days,
        keep_min_per_repo=keep_min_per_repo,
        dry_run=dry_run,
        deleted_snapshots=deleted if not dry_run else len(candidates),
        affected_repositories=affected,
        oldest_kept_at=oldest_dt,
        cutoff=cutoff,
    )


def temporary_snapshot_copy(source: Path) -> Path:  # pragma: no cover - test helper
    handle, name = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    target = Path(name)
    shutil.copy2(source, target)
    return target
