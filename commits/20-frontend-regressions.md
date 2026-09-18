# Commit 20 — test: cover dashboard alert contracts and regressions

Reference implementation commit: `a57b94fe8a9808c43448e88236d511a07e8ecac6`
Apply after: `Commit 19`

## Goal

Add frontend contract coverage and prevent newly created burst rules from replaying old historical bursts.

## Files

### `src/alerts/service.py`

Replace this file with the complete post-commit content below.

````python
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

    # Do not replay an entire repository's burst history when a rule is first
    # created. A two-day lookback still catches a burst discovered between
    # daily collections; after that, the prior evaluation is the watermark.
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
````

### `tests/test_alert_regressions.py`

Replace this file with the complete post-commit content below.

````python
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
    evaluated_at = datetime(2026, 9, 16, tzinfo=UTC)

    initial = await evaluate_burst_rule(
        db_session, rule, [first], evaluated_at=evaluated_at
    )
    repeated = await evaluate_burst_rule(
        db_session, rule, [first, second], evaluated_at=evaluated_at
    )
    assert len(initial) == 1
    assert len(repeated) == 1
    await db_session.commit()

    assert (await list_events(db_session))[1] == 2


async def test_new_burst_rule_does_not_replay_old_history(db_session) -> None:
    rule = await _create(db_session, RuleSpec(kind=BURST_STARTED))
    events = [_burst(date(2026, 8, 1)), _burst(date(2026, 9, 15))]

    inserted = await evaluate_burst_rule(
        db_session,
        rule,
        events,
        evaluated_at=datetime(2026, 9, 16, tzinfo=UTC),
    )
    await db_session.commit()

    assert [event.fingerprint for event in inserted] == ["burst:2026-09-15"]
    assert (await list_events(db_session))[1] == 1


async def test_disabled_milestone_does_not_reserve_its_fingerprint(db_session) -> None:
    rule = await _create(db_session, RuleSpec(kind=STARS_REACHED, threshold=1000))
    rule.enabled = False
    assert await evaluate_milestone_rule(db_session, rule, 1000) is None

    rule.enabled = True
    assert await evaluate_milestone_rule(db_session, rule, 1000) is not None
````

### `tests/test_dashboard_alerts.py`

Create this file with the complete content below.

````python
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def _read(name: str) -> str:
    return (WEB / name).read_text()


def test_alert_dashboard_controls_are_present() -> None:
    html = _read("index.html")
    for element_id in (
        "alerts-toggle",
        "alert-count",
        "alerts-panel",
        "alerts-summary",
        "acknowledge-all",
        "alerts-close",
        "alert-section",
        "alert-view",
        "alert-kind-filter",
        "alert-events",
        "alert-rule-form",
        "alert-rule-repository",
        "alert-rule-kind",
        "alert-rule-threshold",
        "alert-rule-window",
        "alert-rules",
    ):
        assert f'id="{element_id}"' in html


def test_alert_controls_have_accessible_names() -> None:
    html = _read("index.html")
    assert 'aria-label="Open alerts"' in html
    assert 'aria-label="Close alerts"' in html
    assert 'aria-label="Alert section"' in html
    assert 'aria-label="Alert status"' in html
    assert 'aria-label="Filter alerts by type"' in html
    assert '<label>\n              Repository' in html
    assert '<label>\n              Alert type' in html


def test_alert_api_calls_use_expected_relative_routes() -> None:
    app = _read("app.js")
    for route in (
        "${API}/alerts/summary",
        "${API}/alerts/events?${params}",
        "${API}/alerts/events/${eventId}",
        "${API}/alerts/events/acknowledge-all",
        "${API}/alerts/rules?limit=100",
        "${API}/alerts/rules",
        "${API}/alerts/rules/${ruleId}",
    ):
        assert route in app
    assert '"PATCH"' in app
    assert '"POST"' in app
    assert '"DELETE"' in app


def test_alert_polling_pauses_while_document_is_hidden() -> None:
    app = _read("app.js")
    assert "const ALERT_POLL_MS = 30000" in app
    assert 'document.addEventListener("visibilitychange"' in app
    assert "if (document.hidden) stopAlertPolling()" in app
    assert "else startAlertPolling()" in app
    assert "clearInterval(alertPollTimer)" in app


def test_alert_lists_abort_stale_requests() -> None:
    app = _read("app.js")
    assert "alertEventsAbortController.abort()" in app
    assert "alertRulesAbortController.abort()" in app
    assert app.count("new AbortController()") >= 3
    assert app.count('err.name === "AbortError"') >= 3


def test_server_alert_text_is_escaped_before_html_rendering() -> None:
    app = _read("app.js")
    for expression in (
        "escapeHtml(event.title)",
        "escapeHtml(event.message)",
        "escapeHtml(event.repository)",
        "escapeHtml(event.created_at)",
        "escapeHtml(rule.repository)",
        "escapeHtml(ruleCondition(rule))",
    ):
        assert expression in app


def test_rule_form_is_type_aware() -> None:
    app = _read("app.js")
    assert 'kind !== "burst_started"' in app
    assert 'kind === "velocity_above"' in app
    assert 'kind === "stars_reached" ? "1" : "0.01"' in app
    assert 'el("alert-rule-threshold").required = needsThreshold' in app


def test_all_static_javascript_dom_references_resolve() -> None:
    html = _read("index.html")
    app = _read("app.js")
    charts = _read("charts.js")
    static_ids = re.findall(r'\bid="([^"]+)"', html)
    generated_ids = set(re.findall(r'\bid=\\?"([A-Za-z][\w-]+)\\?"', app))
    references = set(re.findall(r'\bel\("([^"]+)"\)', app))
    references.update(re.findall(r'getElementById\("([^"]+)"\)', charts))

    assert len(static_ids) == len(set(static_ids))
    assert references <= set(static_ids) | generated_ids


def test_alert_styles_cover_states_and_mobile_layout() -> None:
    styles = _read("styles.css")
    for selector in (
        ".alert-count",
        ".alerts-panel",
        ".alert-event.unread",
        ".alert-event.read",
        ".delivery.failed",
        ".delivery.sent",
        ".alert-rule-form",
        ".alert-rule.disabled",
        ".btn.danger",
    ):
        assert selector in styles
    mobile = styles[styles.index("@media (max-width: 860px)") :]
    assert ".alert-rule-form" in mobile
    assert "grid-template-columns: 1fr" in mobile


async def test_dashboard_with_alert_markup_is_served(api_client) -> None:
    response = await api_client.get("/")
    assert response.status_code == 200
    assert 'id="alerts-toggle"' in response.text
    assert 'id="alert-rule-form"' in response.text
    assert '<script src="/app.js"></script>' in response.text
````

## Verify

```bash
pytest -q tests/test_alert_service.py tests/test_alert_regressions.py tests/test_dashboard_alerts.py
node --check web/app.js
```

## Commit

```bash
git add -- \
  src/alerts/service.py \
  tests/test_alert_regressions.py \
  tests/test_dashboard_alerts.py
git commit -m 'test: cover dashboard alert contracts and regressions'
```
