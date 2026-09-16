from __future__ import annotations

from dataclasses import dataclass

BURST_STARTED = "burst_started"
VELOCITY_ABOVE = "velocity_above"
STARS_REACHED = "stars_reached"
ALERT_KINDS = frozenset({BURST_STARTED, VELOCITY_ABOVE, STARS_REACHED})
VELOCITY_WINDOWS = frozenset({7, 30, 90})


@dataclass(frozen=True)
class RuleSpec:
    kind: str
    threshold: float | None = None
    window_days: int | None = None


@dataclass(frozen=True)
class AlertCandidate:
    kind: str
    fingerprint: str
    title: str
    message: str
    current_value: float | None = None
    threshold: float | None = None
