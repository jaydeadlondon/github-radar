import json
from datetime import UTC, datetime, timedelta, timezone

import httpx

from alerts.webhook import build_webhook_payload, deliver_event
from db.models import AlertEvent


def _event(created_at: datetime) -> AlertEvent:
    event = AlertEvent(
        id=42,
        rule_id=7,
        repo_id=3,
        repository_full_name="acme/rocket",
        kind="velocity_above",
        fingerprint="velocity:7:25:2026-09-16",
        title="Velocity threshold reached",
        message="acme/rocket crossed 25 stars/day",
        current_value=27.4,
        threshold=25,
        created_at=created_at,
    )
    return event


def test_webhook_payload_is_stable_and_secret_free() -> None:
    payload = build_webhook_payload(_event(datetime(2026, 9, 16, 12, tzinfo=UTC)))

    assert payload == {
        "event_id": 42,
        "kind": "velocity_above",
        "repository": "acme/rocket",
        "title": "Velocity threshold reached",
        "message": "acme/rocket crossed 25 stars/day",
        "current_value": 27.4,
        "threshold": 25,
        "created_at": "2026-09-16T12:00:00Z",
        "repository_url": "https://github.com/acme/rocket",
    }
    assert "webhook" not in payload


def test_webhook_payload_treats_sqlite_naive_timestamp_as_utc() -> None:
    payload = build_webhook_payload(_event(datetime(2026, 9, 16, 12)))
    assert payload["created_at"] == "2026-09-16T12:00:00Z"


def test_webhook_payload_normalizes_aware_timestamp_to_utc() -> None:
    plus_three = timezone(timedelta(hours=3))
    payload = build_webhook_payload(_event(datetime(2026, 9, 16, 15, tzinfo=plus_three)))
    assert payload["created_at"] == "2026-09-16T12:00:00Z"


async def test_delivery_without_url_keeps_event_in_inbox(db_session) -> None:
    event = _event(datetime(2026, 9, 16, 12, tzinfo=UTC))
    event.id = None
    event.rule_id = None
    event.repo_id = None
    db_session.add(event)
    await db_session.flush()

    delivered = await deliver_event(db_session, event, webhook_url="")

    assert delivered is True
    assert event.delivery_status == "inbox_only"
    assert event.delivery_error is None


async def test_successful_webhook_delivery_stores_sent_status(db_session) -> None:
    event = _event(datetime(2026, 9, 16, 12, tzinfo=UTC))
    event.id = None
    event.rule_id = None
    event.repo_id = None
    db_session.add(event)
    await db_session.flush()
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(204)

    delivered = await deliver_event(
        db_session,
        event,
        webhook_url="https://hooks.example.test/radar",
        transport=httpx.MockTransport(handler),
    )

    assert delivered is True
    assert event.delivery_status == "sent"
    assert event.delivery_error is None
    assert captured["event_id"] == event.id
    assert captured["repository"] == "acme/rocket"


async def test_non_success_webhook_response_is_recorded(db_session) -> None:
    event = _event(datetime(2026, 9, 16, 12, tzinfo=UTC))
    event.id = None
    event.rule_id = None
    event.repo_id = None
    db_session.add(event)
    await db_session.flush()

    delivered = await deliver_event(
        db_session,
        event,
        webhook_url="https://hooks.example.test/radar",
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )

    assert delivered is False
    assert event.delivery_status == "failed"
    assert event.delivery_error == "HTTP 503"


async def test_network_error_does_not_store_secret_url(db_session) -> None:
    event = _event(datetime(2026, 9, 16, 12, tzinfo=UTC))
    event.id = None
    event.rule_id = None
    event.repo_id = None
    db_session.add(event)
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-token was refused", request=request)

    delivered = await deliver_event(
        db_session,
        event,
        webhook_url="https://user:secret-token@hooks.example.test/radar",
        transport=httpx.MockTransport(handler),
    )

    assert delivered is False
    assert event.delivery_status == "failed"
    assert event.delivery_error == "ConnectError: webhook request failed"
    assert "secret-token" not in event.delivery_error
