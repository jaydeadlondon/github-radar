"""Dashboard UX and accessibility contract for the v1.0 web interface.

The dashboard is shipped as plain static files, so these tests inspect the
markup, styles and behaviour at the source level.  They guard the promises made
in the v1.0 plan: no silent failures, keyboard access, announced state changes,
readable dates, offline assets and confirmations before destructive actions.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def _read(name: str) -> str:
    return (WEB / name).read_text()


# --- structure & keyboard ---------------------------------------------------


def test_skip_link_and_focusable_main_region() -> None:
    html = _read("index.html")
    assert 'class="skip-link" href="#main"' in html
    assert 'id="main" tabindex="-1"' in html
    assert ".skip-link:focus" in _read("styles.css")


def test_screen_reader_only_helper_is_defined_and_used() -> None:
    css = _read("styles.css")
    assert ".sr-only" in css
    assert "clip: rect(0, 0, 0, 0)" in css
    html = _read("index.html")
    app = _read("app.js")
    assert 'class="sr-only"' in html
    assert "sr-only" in app  # table headers announce their sort target


def test_live_regions_and_roles_announce_updates() -> None:
    html = _read("index.html")
    assert 'id="live-region"' in html
    assert 'aria-live="polite"' in html
    assert 'role="status"' in html
    assert 'id="toasts" role="status"' in html
    app = _read("app.js")
    assert "function announce(" in app
    assert 'setAttribute("role", kind === "error" ? "alert" : "status")' in app


def test_loading_error_and_empty_states_share_one_renderer() -> None:
    app = _read("app.js")
    assert "function setRegionState(" in app
    for kind in ("loading", "empty", "error"):
        assert f'"{kind}"' in app
    assert "setBusy(node, kind === \"loading\")" in app
    assert "aria-busy" in app
    assert app.count("setRegionState(") >= 5
    # Panels that fetch data start as busy and are released when resolved.
    html = _read("index.html")
    assert html.count('aria-busy="true"') >= 3
    assert "setBusy(grid, false)" in app


def test_every_form_control_has_an_accessible_name() -> None:
    html = _read("index.html")
    controls = re.findall(r"<(?:input|select|textarea)\b[^>]*>", html)
    assert controls, "expected form controls in the dashboard"
    for control in controls:
        wrapped = re.search(
            r"<label[^>]*>(?:(?!</label>).)*" + re.escape(control),
            html,
            flags=re.DOTALL,
        )
        assert 'aria-label="' in control or wrapped, control


def test_interactive_cards_and_rows_are_keyboard_reachable() -> None:
    app = _read("app.js")
    assert '<button type="button" class="riser-card"' in app
    assert 'tabindex="0"' in app
    assert 'event.key === "Enter"' in app
    assert 'event.key === " "' in app
    assert "initSegGroup" in app
    assert 'group.addEventListener("keydown"' in app
    assert "ArrowRight" in app and "Home" in app and "End" in app


def test_alerts_panel_manages_focus_and_escape() -> None:
    app = _read("app.js")
    html = _read("index.html")
    assert 'aria-controls="alerts-panel"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-modal="false"' in html
    assert "focusBeforeAlerts" in app
    assert "panel.focus({ preventScroll: true })" in app
    assert 'event.key === "Escape" && state.alertsOpen' in app


def test_sortable_headers_expose_aria_sort() -> None:
    app = _read("app.js")
    assert "aria-sort" in app
    assert '"ascending"' in app and '"descending"' in app and '"none"' in app


# --- visual / motion preferences -------------------------------------------


def test_reduced_motion_is_respected() -> None:
    css = _read("styles.css")
    assert "prefers-reduced-motion: reduce" in css
    assert "animation-duration: 0.001ms" in css
    assert "transition-duration: 0.001ms" in css


def test_mobile_breakpoints_and_touch_targets() -> None:
    css = _read("styles.css")
    assert "@media (max-width: 860px)" in css
    assert "@media (max-width: 560px)" in css
    assert "min-height: 44px" in css
    assert "position: static" in css  # filters stop sticking on small screens


def test_visible_focus_styles_exist_beyond_inputs() -> None:
    css = _read("styles.css")
    assert ":focus-visible" in css
    assert ".riser-card:focus-visible" in css
    assert "th.sortable button.th-sort:focus-visible" in css


# --- behaviour: no silent failures, correct dates, safe destructive ops ----


def test_destructive_actions_require_confirmation() -> None:
    app = _read("app.js")
    assert "Stop tracking ${fullName}?" in app
    assert "Delete this alert rule?" in app
    for prompt in ("window.confirm(",):
        assert prompt in app
    # The confirmation happens before the DELETE request is issued.
    block = app.split("async function changeRepositoryTracking")[1]
    confirmation = block.index("window.confirm(")
    request = block.index('"DELETE"')
    assert confirmation < request


def test_dates_are_rendered_in_local_time_with_a_zone() -> None:
    app = _read("app.js")
    assert "toLocaleString(undefined" in app
    assert 'timeZoneName: "short"' in app
    assert "datetime=\"${escapeHtml(event.created_at)}\"" in app


def test_numbers_follow_the_visitor_locale() -> None:
    app = _read("app.js")
    assert 'new Intl.NumberFormat(undefined' in app
    assert '"en-US"' not in app


def test_failures_are_reported_instead_of_swallowed() -> None:
    app = _read("app.js")
    assert "function describeError(" in app
    assert "noteChartIssue(" in app
    assert "renderChartIssues()" in app
    # No bare `catch (_) { return null }` analytics helpers remain.
    assert "catch (_) {\n    return null;" not in app
    assert "Languages unavailable" in app


def test_theme_defaults_to_the_system_preference() -> None:
    app = _read("app.js")
    assert "prefers-color-scheme: light" in app
    assert "function storedTheme(" in app
    assert 'localStorage.setItem(\n    "radar-theme",' in app


def test_dashboard_assets_stay_offline() -> None:
    for name in ("index.html", "app.js", "charts.js", "styles.css"):
        source = _read(name)
        assert "http://" not in source
        assert "https://" not in source or name == "index.html"


def test_refresh_button_runs_the_shared_refresh_path() -> None:
    app = _read("app.js")
    assert "async function refreshAll()" in app
    assert 'el("refresh-btn").addEventListener("click", refreshAll)' in app
    assert 'button.setAttribute("aria-busy", "true")' in app
