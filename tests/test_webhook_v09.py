import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from alerts.webhook import deliver_event
from config import settings
from db.models import AlertDelivery, AlertEvent, NotificationEndpoint


def _event() -> AlertEvent:
    return AlertEvent(
        repository_full_name="acme/rocket",
        kind="velocity_above",
        fingerprint="velocity:7:25:2026-09-20",
        title="Velocity threshold reached",
        message="acme/rocket crossed 25 stars/day",
        current_value=27.4,
        threshold=25,
        created_at=datetime(2026, 9, 20, 12, tzinfo=UTC),
    )


async def test_webhook_retries_records_each_attempt_and_signs_payload(db_session):
    event = _event()
    db_session.add(event)
    await db_session.flush()
    endpoint = NotificationEndpoint(
        name="test-slack",
        provider="slack",
        url="https://hooks.example.test/slack",
        signing_secret="secret",
    )
    db_session.add(endpoint)
    await db_session.flush()
    calls = {"count": 0}
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        captured["body"] = request.content
        captured["signature"] = request.headers["X-GitHub-Radar-Signature-256"]
        return httpx.Response(503) if calls["count"] == 1 else httpx.Response(204)

    delivered = await deliver_event(
        db_session,
        event,
        webhook_url=endpoint.url,
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        backoff_base_seconds=0,
        provider=endpoint.provider,
        signing_secret=endpoint.signing_secret,
        endpoint=endpoint,
    )

    assert delivered is True
    assert calls["count"] == 2
    expected = hmac.new(b"secret", captured["body"], hashlib.sha256).hexdigest()
    assert captured["signature"] == f"sha256={expected}"
    assert json.loads(captured["body"]) == {
        "text": "Velocity threshold reached: acme/rocket crossed 25 stars/day"
    }
    deliveries = list(
        await db_session.scalars(
            select(AlertDelivery)
            .where(AlertDelivery.event_id == event.id)
            .order_by(AlertDelivery.attempt)
        )
    )
    assert [item.status for item in deliveries] == ["failed", "sent"]
    assert endpoint.failure_count == 0


async def test_endpoint_is_disabled_after_consecutive_failures(db_session, monkeypatch):
    monkeypatch.setattr(settings, "webhook_disable_after_failures", 2)
    event = _event()
    db_session.add(event)
    await db_session.flush()
    endpoint = NotificationEndpoint(
        name="broken",
        provider="generic",
        url="https://hooks.example.test/broken",
    )
    db_session.add(endpoint)
    await db_session.flush()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    assert not await deliver_event(
        db_session,
        event,
        webhook_url=endpoint.url,
        transport=httpx.MockTransport(handler),
        max_attempts=1,
        backoff_base_seconds=0,
        endpoint=endpoint,
    )
    assert not await deliver_event(
        db_session,
        event,
        webhook_url=endpoint.url,
        transport=httpx.MockTransport(handler),
        max_attempts=1,
        backoff_base_seconds=0,
        endpoint=endpoint,
    )

    assert endpoint.failure_count == 2
    assert endpoint.enabled is False
    assert endpoint.disabled_at is not None
