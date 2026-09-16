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
