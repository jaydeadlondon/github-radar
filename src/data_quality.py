"""Validation and normalization for incoming repository snapshots.

The collector deliberately records rejected observations instead of silently
turning them into zero growth.  Accepted observations may carry an anomaly
reason when they are unusually large but still represent a valid GitHub value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class SnapshotQuality(StrEnum):
    ACCEPTED = "accepted"
    ANOMALOUS = "anomalous"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SnapshotCheck:
    status: SnapshotQuality
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status in {SnapshotQuality.ACCEPTED, SnapshotQuality.ANOMALOUS}


def normalize_utc(value: datetime | None) -> datetime:
    """Return an aware UTC datetime for every persisted observation."""

    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def inspect_snapshot(
    *,
    stargazers: int,
    forks: int,
    open_issues: int,
    previous_stars: int | None,
    allow_decrease: bool = False,
    anomaly_ratio: float = 10.0,
    anomaly_min_delta: int = 100,
) -> SnapshotCheck:
    """Validate counts and classify suspicious but usable observations.

    Star decreases are rejected by default because GitHub API failures and
    malformed payloads must never look like real negative growth.  Callers
    handling an explicit GitHub history correction can opt in with
    ``allow_decrease=True``; the observation is then marked anomalous.
    """

    if stargazers < 0 or forks < 0 or open_issues < 0:
        return SnapshotCheck(SnapshotQuality.REJECTED, "negative_count")
    if previous_stars is not None and stargazers < previous_stars:
        if not allow_decrease:
            return SnapshotCheck(SnapshotQuality.REJECTED, "stars_decreased")
        return SnapshotCheck(SnapshotQuality.ANOMALOUS, "stars_decreased_explicit")

    if previous_stars is not None:
        delta = stargazers - previous_stars
        baseline = max(previous_stars, 1)
        if delta >= anomaly_min_delta and delta / baseline >= anomaly_ratio:
            return SnapshotCheck(SnapshotQuality.ANOMALOUS, "large_positive_jump")
    return SnapshotCheck(SnapshotQuality.ACCEPTED)


def sanitize_error(error: BaseException | str, *, max_length: int = 500) -> str:
    """Make an operational error safe to store and display.

    Exception messages can contain URLs, query strings or an Authorization
    header copied by an HTTP client.  Keep the category and useful text while
    removing common credential-bearing forms and bounding the result.
    """

    text = str(error).strip() or type(error).__name__
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+(?:\s+[^\s,;]+)?",
        r"\1[redacted]",
        text,
    )
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[redacted]", text)
    text = re.sub(
        r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"https?://[^\s]+", "[url redacted]", text)
    return text[:max_length]
