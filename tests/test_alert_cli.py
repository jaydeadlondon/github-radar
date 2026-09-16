from __future__ import annotations

import asyncio

from typer.testing import CliRunner

from alerts import STARS_REACHED, AlertCandidate, RuleSpec
from collector.cli import app
from db.alerts import create_event, create_rule, get_event, get_rule, list_rules
from db.base import SessionFactory
from db.repositories import upsert_repository
from github.models import RepoSummary

runner = CliRunner()


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


async def _seed_repo() -> None:
    async with SessionFactory() as session:
        await upsert_repository(session, _summary())
        await session.commit()


async def _rules():
    async with SessionFactory() as session:
        return await list_rules(session)


async def _seed_event() -> tuple[int, int]:
    async with SessionFactory() as session:
        repo = await upsert_repository(session, _summary())
        rule = await create_rule(
            session,
            repo,
            RuleSpec(kind=STARS_REACHED, threshold=1000),
        )
        event = await create_event(
            session,
            rule,
            AlertCandidate(
                kind=STARS_REACHED,
                fingerprint="milestone:1000",
                title="Star milestone reached",
                message="acme/rocket reached 1,000 stars",
                current_value=1001,
                threshold=1000,
            ),
        )
        assert event is not None
        await session.commit()
        return rule.id, event.id


def test_alerts_help_lists_management_and_inbox_commands() -> None:
    result = runner.invoke(app, ["alerts", "--help"])
    assert result.exit_code == 0
    for command in ("add", "list", "enable", "disable", "delete", "events", "acknowledge"):
        assert command in result.output


def test_alerts_add_and_list_velocity_rule() -> None:
    asyncio.run(_seed_repo())

    added = runner.invoke(
        app,
        [
            "alerts",
            "add",
            "acme/rocket",
            "--type",
            "velocity",
            "--threshold",
            "25",
            "--window",
            "7",
        ],
    )
    listed = runner.invoke(app, ["alerts", "list"])

    assert added.exit_code == 0
    assert "Created alert rule" in added.output
    assert listed.exit_code == 0
    assert "acme/rocket" in listed.output
    assert "velocity_above" in listed.output
    assert "25/day (7d)" in listed.output


def test_alerts_add_validates_type_and_condition() -> None:
    asyncio.run(_seed_repo())
    unknown = runner.invoke(
        app, ["alerts", "add", "acme/rocket", "--type", "email"]
    )
    invalid = runner.invoke(
        app,
        [
            "alerts",
            "add",
            "acme/rocket",
            "--type",
            "velocity",
            "--threshold",
            "10",
            "--window",
            "14",
        ],
    )

    assert unknown.exit_code == 2
    assert "burst, velocity or milestone" in unknown.output
    assert invalid.exit_code == 2
    assert "one of 7, 30, 90" in invalid.output


def test_alerts_add_requires_tracked_repository() -> None:
    result = runner.invoke(
        app, ["alerts", "add", "no/such", "--type", "burst"]
    )
    assert result.exit_code == 1
    assert "Repository not tracked" in result.output


def test_alert_rule_enable_disable_and_delete() -> None:
    asyncio.run(_seed_repo())
    added = runner.invoke(
        app, ["alerts", "add", "acme/rocket", "--type", "burst"]
    )
    assert added.exit_code == 0
    rule_id = asyncio.run(_rules())[0][0].id

    disabled = runner.invoke(app, ["alerts", "disable", str(rule_id)])
    async def _is_enabled() -> bool:
        async with SessionFactory() as session:
            rule = await get_rule(session, rule_id)
            assert rule is not None
            return rule.enabled

    assert disabled.exit_code == 0
    assert asyncio.run(_is_enabled()) is False
    enabled = runner.invoke(app, ["alerts", "enable", str(rule_id)])
    assert enabled.exit_code == 0
    assert asyncio.run(_is_enabled()) is True

    deleted = runner.invoke(app, ["alerts", "delete", str(rule_id), "--yes"])
    assert deleted.exit_code == 0
    assert asyncio.run(_rules())[1] == 0


def test_alert_events_and_acknowledge_commands() -> None:
    _rule_id, event_id = asyncio.run(_seed_event())

    listed = runner.invoke(app, ["alerts", "events", "--unread"])
    acknowledged = runner.invoke(app, ["alerts", "acknowledge", str(event_id)])

    async def _acknowledged() -> bool:
        async with SessionFactory() as session:
            event = await get_event(session, event_id)
            assert event is not None
            return event.acknowledged_at is not None

    assert listed.exit_code == 0
    assert "acme/rocket" in listed.output
    assert "stars_reached" in listed.output
    assert acknowledged.exit_code == 0
    assert asyncio.run(_acknowledged()) is True


def test_alert_acknowledge_all_reports_changed_count() -> None:
    asyncio.run(_seed_event())
    result = runner.invoke(app, ["alerts", "acknowledge-all", "--yes"])
    assert result.exit_code == 0
    assert "Acknowledged 1 alert event" in result.output
