# Commit 10 — feat: deliver new alert events to a generic webhook

Reference implementation commit: `b3308c8023705a3bb48146d3d3cdb383ac1fa334`
Apply after: `Commit 09`

## Goal

Deliver webhooks with isolated failures and persist inbox-only, sent, or failed delivery state without leaking target URLs.

## Files

### `src/alerts/webhook.py`

Replace this file with the complete post-commit content below.

````python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from db.alerts import set_delivery_result
from db.models import AlertEvent


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def build_webhook_payload(event: AlertEvent) -> dict[str, Any]:
    """Build the stable, secret-free webhook contract for an alert event."""
    return {
        "event_id": event.id,
        "kind": event.kind,
        "repository": event.repository_full_name,
        "title": event.title,
        "message": event.message,
        "current_value": event.current_value,
        "threshold": event.threshold,
        "created_at": _utc_iso(event.created_at),
        "repository_url": f"https://github.com/{event.repository_full_name}",
    }


def _delivery_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: webhook request failed"


async def deliver_event(
    session: AsyncSession,
    event: AlertEvent,
    *,
    webhook_url: str,
    timeout_seconds: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Deliver one event, persisting status without leaking the destination URL."""
    if not webhook_url.strip():
        await set_delivery_result(session, event, status="inbox_only")
        return True

    try:
        async with httpx.AsyncClient(
            timeout=max(timeout_seconds, 0.1),
            transport=transport,
            follow_redirects=False,
        ) as client:
            response = await client.post(webhook_url, json=build_webhook_payload(event))
            response.raise_for_status()
    except httpx.HTTPError as exc:
        await set_delivery_result(
            session,
            event,
            status="failed",
            error=_delivery_error(exc)[:200],
        )
        return False

    await set_delivery_result(session, event, status="sent")
    return True
````

### `tests/test_alert_webhook.py`

Replace this file with the complete post-commit content below.

````python
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
````

## Verify

```bash
pytest -q tests/test_alert_webhook.py
```

## Commit

```bash
git add -- \
  src/alerts/webhook.py \
  tests/test_alert_webhook.py
git commit -m 'feat: deliver new alert events to a generic webhook'
```
