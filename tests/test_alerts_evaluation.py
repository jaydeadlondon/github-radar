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
        validate_rule(
            RuleSpec(kind=BURST_STARTED, threshold=threshold, window_days=window)
        )


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
