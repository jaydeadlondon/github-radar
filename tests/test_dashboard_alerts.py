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
