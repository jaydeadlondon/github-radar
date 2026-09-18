# Commit 06 — feat: evaluate velocity threshold crossings

Reference implementation commit: `800a32ed3b29acac4d8b1bed68b4fdf0c97cca38`
Apply after: `Commit 05`

## Goal

Evaluate velocity rules only when a configured threshold is crossed from below, while maintaining rule state.

## Files

### `src/alerts/service.py`

Replace this file with the complete post-commit content below.

````python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from alerts.evaluation import milestone_candidate, velocity_candidate
from alerts.types import STARS_REACHED, VELOCITY_ABOVE
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
````

### `tests/test_alert_service.py`

Replace this file with the complete post-commit content below.

````python
from datetime import UTC, datetime

import pytest

from alerts import STARS_REACHED, VELOCITY_ABOVE, RuleSpec
from alerts.service import evaluate_milestone_rule, evaluate_velocity_rule
from db.alerts import create_rule, list_events
from db.repositories import upsert_repository
from github.models import RepoSummary

EVALUATED_AT = datetime(2026, 9, 16, 12, tzinfo=UTC)


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


async def _rule(
    db_session,
    *,
    kind: str = STARS_REACHED,
    threshold: float | None = 1000,
    window_days: int | None = None,
    enabled: bool = True,
):
    repo = await upsert_repository(db_session, _summary())
    return await create_rule(
        db_session,
        repo,
        RuleSpec(kind=kind, threshold=threshold, window_days=window_days),
        enabled=enabled,
    )


async def test_milestone_rule_waits_below_threshold(db_session) -> None:
    rule = await _rule(db_session)

    event = await evaluate_milestone_rule(
        db_session, rule, 999, evaluated_at=EVALUATED_AT
    )

    assert event is None
    assert rule.last_value == 999
    assert rule.last_evaluated_at == EVALUATED_AT
    assert (await list_events(db_session))[1] == 0


async def test_milestone_rule_creates_one_deduplicated_event(db_session) -> None:
    rule = await _rule(db_session)

    first = await evaluate_milestone_rule(db_session, rule, 1000)
    repeated = await evaluate_milestone_rule(db_session, rule, 1200)
    await db_session.commit()

    assert first is not None
    assert first.repository_full_name == "acme/rocket"
    assert first.current_value == 1000
    assert repeated is None
    events, total = await list_events(db_session)
    assert total == 1
    assert events[0].fingerprint == "milestone:1000"


async def test_disabled_milestone_rule_updates_state_without_event(db_session) -> None:
    rule = await _rule(db_session, enabled=False)

    event = await evaluate_milestone_rule(db_session, rule, 2000)

    assert event is None
    assert rule.last_value == 2000
    assert rule.last_evaluated_at is not None


async def test_milestone_evaluator_rejects_other_rule_kind(db_session) -> None:
    rule = await _rule(
        db_session,
        kind=VELOCITY_ABOVE,
        threshold=10,
        window_days=7,
    )

    with pytest.raises(ValueError, match="expected a stars_reached"):
        await evaluate_milestone_rule(db_session, rule, 1000)


async def test_velocity_rule_triggers_once_when_threshold_is_crossed(db_session) -> None:
    rule = await _rule(
        db_session,
        kind=VELOCITY_ABOVE,
        threshold=10,
        window_days=7,
    )

    below = await evaluate_velocity_rule(
        db_session, rule, 9.5, evaluated_at=EVALUATED_AT
    )
    crossed = await evaluate_velocity_rule(
        db_session, rule, 10.5, evaluated_at=EVALUATED_AT
    )
    repeated = await evaluate_velocity_rule(
        db_session, rule, 12, evaluated_at=EVALUATED_AT
    )

    assert below is None
    assert crossed is not None
    assert crossed.fingerprint == "velocity:7:10:2026-09-16"
    assert repeated is None
    assert rule.last_value == 12


async def test_velocity_rule_can_trigger_after_dropping_below_again(db_session) -> None:
    rule = await _rule(
        db_session,
        kind=VELOCITY_ABOVE,
        threshold=10,
        window_days=30,
    )

    first = await evaluate_velocity_rule(
        db_session, rule, 11, evaluated_at=EVALUATED_AT
    )
    await evaluate_velocity_rule(db_session, rule, 8, evaluated_at=EVALUATED_AT)
    second = await evaluate_velocity_rule(
        db_session,
        rule,
        13,
        evaluated_at=datetime(2026, 9, 17, 12, tzinfo=UTC),
    )
    await db_session.commit()

    assert first is not None and second is not None
    events, total = await list_events(db_session)
    assert total == 2
    assert {event.fingerprint for event in events} == {
        "velocity:30:10:2026-09-16",
        "velocity:30:10:2026-09-17",
    }


async def test_disabled_velocity_rule_only_updates_last_value(db_session) -> None:
    rule = await _rule(
        db_session,
        kind=VELOCITY_ABOVE,
        threshold=10,
        window_days=90,
        enabled=False,
    )

    event = await evaluate_velocity_rule(db_session, rule, 20)

    assert event is None
    assert rule.last_value == 20


async def test_velocity_evaluator_requires_complete_velocity_rule(db_session) -> None:
    milestone = await _rule(db_session)
    with pytest.raises(ValueError, match="expected a velocity_above"):
        await evaluate_velocity_rule(db_session, milestone, 20)

    incomplete = await _rule(
        db_session,
        kind=VELOCITY_ABOVE,
        threshold=10,
        window_days=None,
    )
    with pytest.raises(ValueError, match="missing threshold or window_days"):
        await evaluate_velocity_rule(db_session, incomplete, 20)
````

## Verify

```bash
pytest -q tests/test_alert_service.py -k velocity
```

## Commit

```bash
git add -- \
  src/alerts/service.py \
  tests/test_alert_service.py
git commit -m 'feat: evaluate velocity threshold crossings'
```
