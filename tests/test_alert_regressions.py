from datetime import UTC, date, datetime

import pytest

from alerts import BURST_STARTED, STARS_REACHED, VELOCITY_ABOVE, RuleSpec, validate_rule
from alerts.service import (
    evaluate_burst_rule,
    evaluate_milestone_rule,
    evaluate_velocity_rule,
)
from analytics.types import BurstEvent
from db.alerts import create_rule, list_events
from db.repositories import upsert_repository
from github.models import RepoSummary


def _summary() -> RepoSummary:
    return RepoSummary(
        id=1,
        full_name="acme/rocket",
        description="Fast",
        html_url="https://github.com/acme/rocket",
        language="Python",
        stargazers_count=100,
        forks_count=1,
    )


async def _create(db_session, spec: RuleSpec):
    repo = await upsert_repository(db_session, _summary())
    return await create_rule(db_session, repo, spec)


def _burst(day: date) -> BurstEvent:
    return BurstEvent(
        start_day=day,
        end_day=day,
        duration_days=1,
        peak_day=day,
        peak_delta=50,
        total_gained=50,
        severity=5,
    )


def test_unknown_alert_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported alert kind"):
        validate_rule(RuleSpec(kind="magic"))


def test_milestone_rule_rejects_a_velocity_window() -> None:
    with pytest.raises(ValueError, match="do not accept window_days"):
        validate_rule(RuleSpec(kind=STARS_REACHED, threshold=1000, window_days=7))


async def test_same_fingerprint_is_allowed_for_different_rules(db_session) -> None:
    first = await _create(db_session, RuleSpec(kind=STARS_REACHED, threshold=1000))
    second = await _create(db_session, RuleSpec(kind=STARS_REACHED, threshold=1000))

    assert await evaluate_milestone_rule(db_session, first, 1001) is not None
    assert await evaluate_milestone_rule(db_session, second, 1001) is not None
    await db_session.commit()

    events, total = await list_events(db_session)
    assert total == 2
    assert {event.rule_id for event in events} == {first.id, second.id}


async def test_duplicate_event_does_not_poison_the_transaction(db_session) -> None:
    first = await _create(db_session, RuleSpec(kind=STARS_REACHED, threshold=1000))
    second = await _create(db_session, RuleSpec(kind=STARS_REACHED, threshold=2000))

    assert await evaluate_milestone_rule(db_session, first, 1000) is not None
    assert await evaluate_milestone_rule(db_session, first, 1100) is None
    assert await evaluate_milestone_rule(db_session, second, 2000) is not None
    await db_session.commit()

    assert (await list_events(db_session))[1] == 2


async def test_velocity_recross_on_same_day_is_deduplicated(db_session) -> None:
    rule = await _create(
        db_session,
        RuleSpec(kind=VELOCITY_ABOVE, threshold=10, window_days=7),
    )
    when = datetime(2026, 9, 16, 10, tzinfo=UTC)

    assert await evaluate_velocity_rule(db_session, rule, 11, evaluated_at=when)
    assert await evaluate_velocity_rule(db_session, rule, 8, evaluated_at=when) is None
    assert await evaluate_velocity_rule(db_session, rule, 12, evaluated_at=when) is None
    await db_session.commit()

    assert (await list_events(db_session))[1] == 1


async def test_velocity_recross_on_later_day_creates_another_event(db_session) -> None:
    rule = await _create(
        db_session,
        RuleSpec(kind=VELOCITY_ABOVE, threshold=10, window_days=7),
    )

    assert await evaluate_velocity_rule(
        db_session, rule, 11, evaluated_at=datetime(2026, 9, 16, tzinfo=UTC)
    )
    assert await evaluate_velocity_rule(
        db_session, rule, 8, evaluated_at=datetime(2026, 9, 16, 12, tzinfo=UTC)
    ) is None
    assert await evaluate_velocity_rule(
        db_session, rule, 12, evaluated_at=datetime(2026, 9, 17, tzinfo=UTC)
    )
    await db_session.commit()

    assert (await list_events(db_session))[1] == 2


async def test_repeated_burst_history_only_adds_new_start_dates(db_session) -> None:
    rule = await _create(db_session, RuleSpec(kind=BURST_STARTED))
    first = _burst(date(2026, 9, 15))
    second = _burst(date(2026, 9, 16))

    assert len(await evaluate_burst_rule(db_session, rule, [first])) == 1
    assert len(await evaluate_burst_rule(db_session, rule, [first, second])) == 1
    await db_session.commit()

    assert (await list_events(db_session))[1] == 2


async def test_disabled_milestone_does_not_reserve_its_fingerprint(db_session) -> None:
    rule = await _create(db_session, RuleSpec(kind=STARS_REACHED, threshold=1000))
    rule.enabled = False
    assert await evaluate_milestone_rule(db_session, rule, 1000) is None

    rule.enabled = True
    assert await evaluate_milestone_rule(db_session, rule, 1000) is not None
