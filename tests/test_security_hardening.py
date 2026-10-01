"""v1.0 security checklist coverage."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.app import SECURITY_HEADERS
from config import ConfigurationError, Settings, validate_runtime_configuration
from security import UnsafeURL, redact_secret, validate_outbound_url, validate_webhook_url

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/hook",
        "https:///hook",
        "https://user:pass@example.com/hook",
        "http://localhost:8000/hook",
        "http://127.0.0.1:8000/hook",
        "http://[::1]/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/hook",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_unsafe_webhook_targets_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeURL):
        validate_webhook_url(url)


def test_public_webhook_targets_are_accepted() -> None:
    assert validate_webhook_url("https://hooks.slack.com/services/x") == (
        "https://hooks.slack.com/services/x"
    )


def test_dns_rebinding_is_blocked_at_delivery_time(monkeypatch) -> None:
    import security

    def _private(hostname: str):
        return [ipaddress.ip_address("10.1.2.3")]

    monkeypatch.setattr(security, "_resolve", _private)
    with pytest.raises(UnsafeURL):
        validate_outbound_url("https://rebind.example.com/hook")

    def _public(hostname: str):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(security, "_resolve", _public)
    assert validate_outbound_url("https://rebind.example.com/hook")


def test_unresolvable_hosts_are_left_to_the_http_client(monkeypatch) -> None:
    import security

    monkeypatch.setattr(security, "_resolve", lambda hostname: [])
    assert validate_outbound_url("https://does-not-resolve.example.test/hook")


async def test_delivery_to_a_private_resolving_host_is_blocked(
    db_session, monkeypatch
) -> None:
    import httpx

    import security
    from alerts.webhook import deliver_event
    from db.models import AlertEvent

    monkeypatch.setattr(
        security,
        "_resolve",
        lambda hostname: [ipaddress.ip_address("192.168.1.10")],
    )
    event = AlertEvent(
        rule_id=None,
        repo_id=None,
        repository_full_name="acme/rocket",
        kind="stars_reached",
        fingerprint="fp-private",
        title="Test",
        message="Test",
        created_at=datetime.now(UTC),
    )
    db_session.add(event)
    await db_session.flush()

    delivered = await deliver_event(
        db_session,
        event,
        webhook_url="https://rebind.example.com/hook",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )

    assert delivered is False
    assert event.delivery_status == "failed"
    assert event.delivery_error == "webhook target address is not allowed"


def test_secret_redaction_masks_credentials() -> None:
    assert redact_secret("token ghp_" + "a" * 30) == "token [redacted-github-token]"
    assert "[redacted-api-key]" in redact_secret("sk-" + "b" * 24)
    assert "[redacted]" in redact_secret("X-API-Key: super-secret")


async def test_endpoint_payload_never_exposes_url_or_secret(api_client) -> None:
    payload = {
        "name": "ops",
        "provider": "generic",
        "url": "https://hooks.example.test/radar",
        "signing_secret": "top-secret-value",
    }
    response = await api_client.post("/api/v1/alerts/endpoints", json=payload)
    body = response.json()
    assert "url" not in body
    assert "signing_secret" not in body
    assert body["url_configured"] is True
    assert "top-secret-value" not in response.text


async def test_ops_config_never_returns_key_values(api_client, monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "api_key", "read-secret")
    monkeypatch.setattr(settings, "admin_api_key", "admin-secret")
    response = await api_client.get("/api/v1/ops/config")
    assert response.status_code == 200
    assert "read-secret" not in response.text
    assert "admin-secret" not in response.text


async def test_oversized_request_is_rejected(api_client, monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "max_request_bytes", 64)
    response = await api_client.post(
        "/api/v1/alerts/rules",
        content=b"x" * 128,
        headers={"content-type": "application/json", "content-length": "128"},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["type"] == "payload_too_large"
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_security_headers_are_present(api_client) -> None:
    response = await api_client.get("/health")
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


async def test_errors_do_not_expose_tracebacks(api_client) -> None:
    response = await api_client.get("/api/v1/repos/no/such")
    assert "Traceback" not in response.text
    assert "site-packages" not in response.text


def test_production_refuses_unsafe_configuration() -> None:
    with pytest.raises(ConfigurationError):
        validate_runtime_configuration(
            Settings(
                environment="production",
                api_auth_enabled=True,
                api_key="k",
                admin_api_key="a",
                github_token="t",
                cors_origins=["*"],
            )
        )
    validate_runtime_configuration(
        Settings(
            environment="production",
            api_auth_enabled=True,
            api_key="k",
            admin_api_key="a",
            github_token="t",
            cors_origins=["https://radar.example.test"],
        )
    )


def test_startup_never_runs_migrations() -> None:
    """Schema changes are explicit commands, never import/startup side effects."""

    for relative in ("src/api/app.py", "src/collector/worker.py"):
        source = (ROOT / relative).read_text()
        assert "create_all" not in source, relative
        assert "alembic" not in source.lower(), relative


def test_dashboard_assets_are_offline() -> None:
    """The dashboard must not depend on CDNs or any other remote asset."""

    for relative in ("web/index.html", "web/app.js", "web/charts.js", "web/styles.css"):
        source = (ROOT / relative).read_text()
        assert "http://" not in source, relative
        # https://github.com links are data, not assets; only check loaded URLs.
        for line in source.splitlines():
            lowered = line.lower()
            if "https://" in lowered and any(
                marker in lowered for marker in ('src="http', "href=\"http", "@import url(http")
            ):
                raise AssertionError(f"remote asset reference in {relative}: {line}")


def test_redaction_keeps_timestamps_readable() -> None:
    stamp = datetime.now(UTC).isoformat()
    assert stamp in redact_secret(f"failed at {stamp}")


def test_delivery_errors_cannot_carry_credentials() -> None:
    """Stored delivery errors are built from safe parts and then redacted."""

    import httpx

    from alerts.webhook import _delivery_error

    request = httpx.Request(
        "POST", "https://hooks.example.com/services/ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    )
    transport_error = httpx.ConnectError("unreachable", request=request)
    message = _delivery_error(transport_error)
    assert "ghp_" not in message
    assert "hooks.example.com" not in message
    assert message.startswith("ConnectError")

    response = httpx.Response(503, request=request)
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=response
    )
    assert _delivery_error(status_error) == "HTTP 503"
