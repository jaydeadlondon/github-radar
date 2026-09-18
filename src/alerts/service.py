from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from alerts.evaluation import burst_candidates, milestone_candidate, velocity_candidate
from alerts.types import BURST_STARTED, STARS_REACHED, VELOCITY_ABOVE
from analytics.types import BurstEvent
from db.alerts import create_event
from db.models import AlertEvent, AlertRule


def _evaluation_time(value: datetime | None) -> datetime:
    return value or datetime.now(UTC)


async def evaluate_milestone_rule(
    session: AsyncSession,
    rule: AlertRule,
    current_stars: int,
    *,
    evaluated_at: datetime | None = None,
) -> AlertEvent | None:
    if rule.kind != STARS_REACHED:
        raise ValueError("expected a stars_reached rule")
    if rule.threshold is None:
        raise ValueError("stars_reached rule is missing its threshold")

    rule.last_value = float(current_stars)
    rule.last_evaluated_at = _evaluation_time(evaluated_at)
    if not rule.enabled:
        return None

    candidate = milestone_candidate(
        rule.repository.full_name,
        current_stars,
        rule.threshold,
    )
    if candidate is None:
        return None
    return await create_event(session, rule, candidate)


async def evaluate_burst_rule(
    session: AsyncSession,
    rule: AlertRule,
    events: Sequence[BurstEvent],
    *,
    evaluated_at: datetime | None = None,
) -> list[AlertEvent]:
    if rule.kind != BURST_STARTED:
        raise ValueError("expected a burst_started rule")

    now = _evaluation_time(evaluated_at)
    previous_evaluation = rule.last_evaluated_at
    rule.last_evaluated_at = now
    if not rule.enabled:
        return []

    cutoff_day = (
        previous_evaluation.date()
        if previous_evaluation is not None
        else now.date() - timedelta(days=2)
    )
    recent_events = [event for event in events if event.end_day >= cutoff_day]
    inserted: list[AlertEvent] = []
    for candidate in burst_candidates(rule.repository.full_name, recent_events):
        event = await create_event(session, rule, candidate)
        if event is not None:
            inserted.append(event)
    return inserted


async def evaluate_velocity_rule(
    session: AsyncSession,
    rule: AlertRule,
    current_velocity: float,
    *,
    evaluated_at: datetime | None = None,
) -> AlertEvent | None:
    if rule.kind != VELOCITY_ABOVE:
        raise ValueError("expected a velocity_above rule")
    if rule.threshold is None or rule.window_days is None:
        raise ValueError("velocity_above rule is missing threshold or window_days")

    previous_velocity = rule.last_value
    now = _evaluation_time(evaluated_at)
    rule.last_value = float(current_velocity)
    rule.last_evaluated_at = now
    if not rule.enabled:
        return None

    candidate = velocity_candidate(
        rule.repository.full_name,
        current_velocity,
        rule.threshold,
        previous_velocity,
        rule.window_days,
        evaluation_day=now.date(),
    )
    if candidate is None:
        return None
    return await create_event(session, rule, candidate)
