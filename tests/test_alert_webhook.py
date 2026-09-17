from datetime import UTC, datetime, timedelta, timezone

from alerts.webhook import build_webhook_payload
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
    payload = build_webhook_payload(
        _event(datetime(2026, 9, 16, 15, tzinfo=plus_three))
    )
    assert payload["created_at"] == "2026-09-16T12:00:00Z"
