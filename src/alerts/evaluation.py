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
    if spec.kind not in ALERT_KINDS:
        raise ValueError(f"unsupported alert kind: {spec.kind}")

    if spec.kind == BURST_STARTED:
        if spec.threshold is not None or spec.window_days is not None:
            raise ValueError(
                "burst_started rules do not accept threshold or window_days"
            )
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
