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
