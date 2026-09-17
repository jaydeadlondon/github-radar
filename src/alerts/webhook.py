from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from db.models import AlertEvent


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def build_webhook_payload(event: AlertEvent) -> dict[str, Any]:
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
