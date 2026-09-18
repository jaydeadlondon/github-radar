# Commit 04 — feat: add alert rule and event storage operations

Reference implementation commit: `54134ca393a1b976a458d1df9933ca8d9c585954`
Apply after: `Commit 03`

## Goal

Add asynchronous rule/event storage operations, pagination, acknowledgement, summaries, delivery state, and atomic deduplication.

## Files

### `src/db/alerts.py`

Create this file with the complete content below.

````python
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
````

### `tests/test_alert_storage.py`

Create this file with the complete content below.

````python
from datetime import UTC, datetime, timedelta

from alerts import STARS_REACHED, AlertCandidate, RuleSpec
from db.alerts import (
    acknowledge_all_events,
    alert_summary,
    create_event,
    create_rule,
    delete_rule,
    get_event,
    get_rule,
    list_enabled_rules,
    list_events,
    list_rules,
    set_delivery_result,
    set_event_acknowledged,
)
from db.repositories import upsert_repository
from github.models import RepoSummary


def _summary(full_name: str = "acme/rocket") -> RepoSummary:
    return RepoSummary(
        id=1,
        full_name=full_name,
        description="Fast",
        html_url=f"https://github.com/{full_name}",
        language="Python",
        stargazers_count=100,
        forks_count=1,
    )


def _candidate(fingerprint: str = "milestone:1000") -> AlertCandidate:
    return AlertCandidate(
        kind=STARS_REACHED,
        fingerprint=fingerprint,
        title="Star milestone reached",
        message="acme/rocket reached 1,000 stars",
        current_value=1001,
        threshold=1000,
    )


async def _make_rule(db_session, full_name: str = "acme/rocket"):
    repo = await upsert_repository(db_session, _summary(full_name))
    rule = await create_rule(
        db_session,
        repo,
        RuleSpec(kind=STARS_REACHED, threshold=1000),
    )
    return repo, rule


async def test_create_get_and_list_rules(db_session) -> None:
    repo, rule = await _make_rule(db_session)
    await db_session.commit()

    found = await get_rule(db_session, rule.id)
    rules, total = await list_rules(db_session, repo_id=repo.id, enabled=True)

    assert found is not None
    assert found.repository.full_name == "acme/rocket"
    assert total == 1
    assert [item.id for item in rules] == [rule.id]


async def test_list_enabled_rules_filters_repositories_and_disabled_rules(db_session) -> None:
    first_repo, first = await _make_rule(db_session, "acme/first")
    second_repo, second = await _make_rule(db_session, "acme/second")
    second.enabled = False
    await db_session.commit()

    rules = await list_enabled_rules(db_session, [first_repo.id, second_repo.id])

    assert [item.id for item in rules] == [first.id]


async def test_delete_rule_keeps_event_history(db_session) -> None:
    _repo, rule = await _make_rule(db_session)
    event = await create_event(db_session, rule, _candidate())
    assert event is not None
    event_id = event.id
    await delete_rule(db_session, rule)
    await db_session.commit()
    db_session.expire_all()

    assert await get_rule(db_session, rule.id) is None
    stored = await get_event(db_session, event_id)
    assert stored is not None
    assert stored.rule_id is None


async def test_create_event_is_atomic_and_deduplicated(db_session) -> None:
    _repo, rule = await _make_rule(db_session)

    first = await create_event(db_session, rule, _candidate())
    duplicate = await create_event(db_session, rule, _candidate())
    different = await create_event(db_session, rule, _candidate("milestone:2000"))
    await db_session.commit()

    assert first is not None
    assert duplicate is None
    assert different is not None
    events, total = await list_events(db_session)
    assert total == 2
    assert {event.fingerprint for event in events} == {
        "milestone:1000",
        "milestone:2000",
    }


async def test_list_events_filters_and_paginates(db_session) -> None:
    _repo, rule = await _make_rule(db_session)
    first = await create_event(db_session, rule, _candidate("milestone:1000"))
    second = await create_event(db_session, rule, _candidate("milestone:2000"))
    assert first is not None and second is not None
    await set_event_acknowledged(
        db_session,
        first,
        True,
        now=datetime(2026, 9, 16, tzinfo=UTC),
    )
    await db_session.commit()

    unread, unread_total = await list_events(db_session, acknowledged=False)
    acknowledged, acknowledged_total = await list_events(db_session, acknowledged=True)
    page, total = await list_events(db_session, limit=1, offset=1)

    assert unread_total == 1 and unread[0].id == second.id
    assert acknowledged_total == 1 and acknowledged[0].id == first.id
    assert total == 2 and len(page) == 1


async def test_acknowledge_all_and_summary(db_session) -> None:
    _repo, rule = await _make_rule(db_session)
    assert await create_event(db_session, rule, _candidate("one")) is not None
    assert await create_event(db_session, rule, _candidate("two")) is not None
    await db_session.commit()

    active, unread, last_at = await alert_summary(db_session)
    changed = await acknowledge_all_events(
        db_session, now=datetime.now(UTC) - timedelta(seconds=1)
    )
    await db_session.commit()
    active_after, unread_after, _ = await alert_summary(db_session)

    assert (active, unread) == (1, 2)
    assert last_at is not None
    assert changed == 2
    assert (active_after, unread_after) == (1, 0)


async def test_delivery_result_is_stored_and_error_can_be_cleared(db_session) -> None:
    _repo, rule = await _make_rule(db_session)
    event = await create_event(db_session, rule, _candidate())
    assert event is not None

    await set_delivery_result(db_session, event, status="failed", error="timeout")
    assert event.delivery_status == "failed"
    assert event.delivery_error == "timeout"
    await set_delivery_result(db_session, event, status="sent")
    assert event.delivery_status == "sent"
    assert event.delivery_error is None
````

## Verify

```bash
pytest -q tests/test_alert_storage.py
ruff check src/db/alerts.py tests/test_alert_storage.py
```

## Commit

```bash
git add -- \
  src/db/alerts.py \
  tests/test_alert_storage.py
git commit -m 'feat: add alert rule and event storage operations'
```
