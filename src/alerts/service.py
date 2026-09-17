from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from alerts.evaluation import milestone_candidate
from alerts.types import STARS_REACHED
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
