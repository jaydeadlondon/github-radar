# Commit 01 — feat: add alert domain types and pure evaluators

Reference implementation commit: `1dfe4bbc2f4ce12f18447054d0138fd45987e0f8`
Apply after: `origin/main@ed0c79d8`

## Goal

Define the supported alert kinds, normalized rule specifications, stable event candidates, and pure evaluators.

## Files

### `src/alerts/__init__.py`

Create this file with the complete content below.

````python
from alerts.evaluation import (
    burst_candidates,
    milestone_candidate,
    validate_rule,
    velocity_candidate,
)
from alerts.types import (
    ALERT_KINDS,
    BURST_STARTED,
    STARS_REACHED,
    VELOCITY_ABOVE,
    AlertCandidate,
    RuleSpec,
)

__all__ = [
    "ALERT_KINDS",
    "BURST_STARTED",
    "STARS_REACHED",
    "VELOCITY_ABOVE",
    "AlertCandidate",
    "RuleSpec",
    "burst_candidates",
    "milestone_candidate",
    "validate_rule",
    "velocity_candidate",
]
````

### `src/alerts/evaluation.py`

Create this file with the complete content below.

````python
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from alerts.types import (
    ALERT_KINDS,
    BURST_STARTED,
    STARS_REACHED,
    VELOCITY_ABOVE,
    VELOCITY_WINDOWS,
    AlertCandidate,
    RuleSpec,
)
from analytics.types import BurstEvent


def validate_rule(spec: RuleSpec) -> RuleSpec:
    """Validate and normalize one alert rule specification."""
    if spec.kind not in ALERT_KINDS:
        raise ValueError(f"unsupported alert kind: {spec.kind}")

    if spec.kind == BURST_STARTED:
        if spec.threshold is not None or spec.window_days is not None:
            raise ValueError("burst_started rules do not accept threshold or window_days")
        return spec

    if spec.threshold is None or spec.threshold <= 0:
        raise ValueError(f"{spec.kind} rules require a positive threshold")

    if spec.kind == STARS_REACHED:
        if not float(spec.threshold).is_integer():
            raise ValueError("stars_reached threshold must be a whole number")
        if spec.window_days is not None:
            raise ValueError("stars_reached rules do not accept window_days")
        return RuleSpec(kind=spec.kind, threshold=float(spec.threshold))

    if spec.window_days not in VELOCITY_WINDOWS:
        raise ValueError("velocity_above window_days must be one of 7, 30, 90")
    return RuleSpec(
        kind=spec.kind,
        threshold=float(spec.threshold),
        window_days=spec.window_days,
    )


def milestone_candidate(
    full_name: str,
    current_stars: int,
    threshold: float,
) -> AlertCandidate | None:
    if current_stars < threshold:
        return None
    milestone = int(threshold)
    return AlertCandidate(
        kind=STARS_REACHED,
        fingerprint=f"milestone:{milestone}",
        title="Star milestone reached",
        message=f"{full_name} reached {milestone:,} stars",
        current_value=float(current_stars),
        threshold=float(threshold),
    )


def velocity_candidate(
    full_name: str,
    current_velocity: float,
    threshold: float,
    previous_velocity: float | None,
    window_days: int,
    *,
    evaluation_day: date | None = None,
) -> AlertCandidate | None:
    crossed = current_velocity >= threshold and (
        previous_velocity is None or previous_velocity < threshold
    )
    if not crossed:
        return None
    suffix = evaluation_day.isoformat() if evaluation_day else f"{current_velocity:g}"
    return AlertCandidate(
        kind=VELOCITY_ABOVE,
        fingerprint=f"velocity:{window_days}:{threshold:g}:{suffix}",
        title="Velocity threshold reached",
        message=(
            f"{full_name} crossed {threshold:g} stars/day over {window_days} days "
            f"({current_velocity:g} stars/day)"
        ),
        current_value=float(current_velocity),
        threshold=float(threshold),
    )


def burst_candidates(
    full_name: str,
    events: Sequence[BurstEvent],
) -> list[AlertCandidate]:
    return [
        AlertCandidate(
            kind=BURST_STARTED,
            fingerprint=f"burst:{event.start_day.isoformat()}",
            title="New star burst detected",
            message=(
                f"{full_name} started a burst on {event.start_day.isoformat()} "
                f"with a peak of +{event.peak_delta:,} stars/day"
            ),
            current_value=float(event.peak_delta),
        )
        for event in events
    ]
````

### `src/alerts/types.py`

Create this file with the complete content below.

````python
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
````

### `tests/test_alerts_evaluation.py`

Create this file with the complete content below.

````python
from datetime import date

import pytest

from alerts import (
    BURST_STARTED,
    STARS_REACHED,
    VELOCITY_ABOVE,
    RuleSpec,
    burst_candidates,
    milestone_candidate,
    validate_rule,
    velocity_candidate,
)
from analytics.types import BurstEvent


def test_validate_burst_rule() -> None:
    assert validate_rule(RuleSpec(kind=BURST_STARTED)) == RuleSpec(kind=BURST_STARTED)


@pytest.mark.parametrize("threshold,window", [(1, None), (None, 7), (1, 7)])
def test_burst_rule_rejects_condition_fields(threshold, window) -> None:
    with pytest.raises(ValueError, match="do not accept"):
        validate_rule(RuleSpec(kind=BURST_STARTED, threshold=threshold, window_days=window))


@pytest.mark.parametrize("window", [7, 30, 90])
def test_validate_velocity_rule(window: int) -> None:
    assert validate_rule(
        RuleSpec(kind=VELOCITY_ABOVE, threshold=12, window_days=window)
    ) == RuleSpec(kind=VELOCITY_ABOVE, threshold=12.0, window_days=window)


@pytest.mark.parametrize("window", [None, 1, 14, 365])
def test_velocity_rule_rejects_invalid_window(window: int | None) -> None:
    with pytest.raises(ValueError, match="one of 7, 30, 90"):
        validate_rule(RuleSpec(kind=VELOCITY_ABOVE, threshold=12, window_days=window))


@pytest.mark.parametrize("threshold", [None, 0, -1])
def test_threshold_rules_require_positive_threshold(threshold: float | None) -> None:
    with pytest.raises(ValueError, match="positive threshold"):
        validate_rule(RuleSpec(kind=STARS_REACHED, threshold=threshold))


def test_milestone_rule_requires_whole_number() -> None:
    with pytest.raises(ValueError, match="whole number"):
        validate_rule(RuleSpec(kind=STARS_REACHED, threshold=99.5))


def test_milestone_candidate_triggers_at_threshold() -> None:
    candidate = milestone_candidate("acme/rocket", 1000, 1000)
    assert candidate is not None
    assert candidate.kind == STARS_REACHED
    assert candidate.fingerprint == "milestone:1000"
    assert "1,000 stars" in candidate.message


def test_milestone_candidate_waits_below_threshold() -> None:
    assert milestone_candidate("acme/rocket", 999, 1000) is None


def test_velocity_candidate_only_triggers_on_crossing() -> None:
    assert velocity_candidate("acme/rocket", 9.9, 10, 8, 7) is None
    candidate = velocity_candidate("acme/rocket", 10.1, 10, 9.9, 7)
    assert candidate is not None
    assert candidate.kind == VELOCITY_ABOVE
    assert candidate.threshold == 10.0
    assert "10.1 stars/day" in candidate.message
    assert velocity_candidate("acme/rocket", 12, 10, 11, 7) is None


def test_velocity_candidate_triggers_on_first_evaluation_above_threshold() -> None:
    assert velocity_candidate("acme/rocket", 12, 10, None, 30) is not None


def test_burst_candidates_have_stable_start_date_fingerprints() -> None:
    event = BurstEvent(
        start_day=date(2026, 9, 10),
        end_day=date(2026, 9, 12),
        duration_days=3,
        peak_day=date(2026, 9, 11),
        peak_delta=250,
        total_gained=600,
        severity=4.2,
    )
    candidate = burst_candidates("acme/rocket", [event])[0]
    assert candidate.kind == BURST_STARTED
    assert candidate.fingerprint == "burst:2026-09-10"
    assert "+250 stars/day" in candidate.message
````

## Verify

```bash
pytest -q tests/test_alerts_evaluation.py
ruff check src/alerts tests/test_alerts_evaluation.py
```

## Commit

```bash
git add -- \
  src/alerts/__init__.py \
  src/alerts/evaluation.py \
  src/alerts/types.py \
  tests/test_alerts_evaluation.py
git commit -m 'feat: add alert domain types and pure evaluators'
```
