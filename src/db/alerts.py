from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from alerts.types import AlertCandidate, RuleSpec
from db.models import AlertEvent, AlertRule, Repository


async def create_rule(
    session: AsyncSession,
    repo: Repository,
    spec: RuleSpec,
    *,
    enabled: bool = True,
) -> AlertRule:
    rule = AlertRule(
        repository=repo,
        kind=spec.kind,
        threshold=spec.threshold,
        window_days=spec.window_days,
        enabled=enabled,
    )
    session.add(rule)
    await session.flush()
    return rule


async def get_rule(session: AsyncSession, rule_id: int) -> AlertRule | None:
    return await session.scalar(
        select(AlertRule)
        .options(selectinload(AlertRule.repository))
        .where(AlertRule.id == rule_id)
    )


async def list_rules(
    session: AsyncSession,
    *,
    repo_id: int | None = None,
    enabled: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AlertRule], int]:
    filters = []
    if repo_id is not None:
        filters.append(AlertRule.repo_id == repo_id)
    if enabled is not None:
        filters.append(AlertRule.enabled.is_(enabled))

    total = await session.scalar(select(func.count(AlertRule.id)).where(*filters))
    rows = await session.scalars(
        select(AlertRule)
        .options(selectinload(AlertRule.repository))
        .where(*filters)
        .order_by(AlertRule.created_at.desc(), AlertRule.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)


async def list_enabled_rules(
    session: AsyncSession,
    repo_ids: Sequence[int],
) -> list[AlertRule]:
    ids = list(dict.fromkeys(repo_ids))
    if not ids:
        return []
    rows = await session.scalars(
        select(AlertRule)
        .options(selectinload(AlertRule.repository))
        .where(AlertRule.repo_id.in_(ids), AlertRule.enabled.is_(True))
        .order_by(AlertRule.id)
    )
    return list(rows)


async def delete_rule(session: AsyncSession, rule: AlertRule) -> None:
    await session.delete(rule)
    await session.flush()


async def create_event(
    session: AsyncSession,
    rule: AlertRule,
    candidate: AlertCandidate,
) -> AlertEvent | None:
    event = AlertEvent(
        rule_id=rule.id,
        repo_id=rule.repo_id,
        repository_full_name=rule.repository.full_name,
        kind=candidate.kind,
        fingerprint=candidate.fingerprint,
        title=candidate.title,
        message=candidate.message,
        current_value=candidate.current_value,
        threshold=candidate.threshold,
    )
    try:
        async with session.begin_nested():
            session.add(event)
            await session.flush()
    except IntegrityError:
        return None
    return event


async def get_event(session: AsyncSession, event_id: int) -> AlertEvent | None:
    return await session.get(AlertEvent, event_id)


async def list_events(
    session: AsyncSession,
    *,
    repository: str | None = None,
    kind: str | None = None,
    acknowledged: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AlertEvent], int]:
    filters = []
    if repository:
        filters.append(AlertEvent.repository_full_name == repository)
    if kind:
        filters.append(AlertEvent.kind == kind)
    if acknowledged is True:
        filters.append(AlertEvent.acknowledged_at.is_not(None))
    elif acknowledged is False:
        filters.append(AlertEvent.acknowledged_at.is_(None))

    total = await session.scalar(select(func.count(AlertEvent.id)).where(*filters))
    rows = await session.scalars(
        select(AlertEvent)
        .where(*filters)
        .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)


async def set_event_acknowledged(
    session: AsyncSession,
    event: AlertEvent,
    acknowledged: bool,
    *,
    now: datetime | None = None,
) -> AlertEvent:
    event.acknowledged_at = (now or datetime.now(UTC)) if acknowledged else None
    await session.flush()
    return event


async def acknowledge_all_events(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    result = await session.execute(
        update(AlertEvent)
        .where(AlertEvent.acknowledged_at.is_(None))
        .values(acknowledged_at=now or datetime.now(UTC))
    )
    return int(result.rowcount or 0)


async def alert_summary(session: AsyncSession) -> tuple[int, int, datetime | None]:
    active_rules = await session.scalar(
        select(func.count(AlertRule.id)).where(AlertRule.enabled.is_(True))
    )
    unread_events = await session.scalar(
        select(func.count(AlertEvent.id)).where(AlertEvent.acknowledged_at.is_(None))
    )
    last_event_at = await session.scalar(select(func.max(AlertEvent.created_at)))
    return int(active_rules or 0), int(unread_events or 0), last_event_at


async def set_delivery_result(
    session: AsyncSession,
    event: AlertEvent,
    *,
    status: str,
    error: str | None = None,
) -> None:
    event.delivery_status = status
    event.delivery_error = error
    await session.flush()
