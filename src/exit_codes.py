from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Documented exit codes of every ``radar`` command."""

    OK = 0
    """Command completed successfully."""

    ERROR = 1
    """Runtime failure: not found, GitHub error, failed job or delivery."""

    USAGE = 2
    """Usage error: invalid arguments, unsupported format, unsafe URL."""

    CONFIG = 3
    """Configuration error: unsafe production configuration, bad settings."""

    DATABASE = 4
    """Database error: missing database, failed migration, backup/restore."""

    INTERRUPTED = 130
    """Interrupted by the user (Ctrl+C or an aborted confirmation)."""


class RadarError(Exception):
    exit_code: ExitCode = ExitCode.ERROR

    def __init__(self, message: str, *, exit_code: ExitCode | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class UsageError(RadarError):
    exit_code = ExitCode.USAGE


class ConfigurationFailure(RadarError):
    exit_code = ExitCode.CONFIG


class DatabaseUnavailableError(RadarError):
    exit_code = ExitCode.DATABASE
