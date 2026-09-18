# Commit 09 — feat: configure optional alert webhook delivery

Reference implementation commit: `890656755a6fe5feb3c24a821f2a0180550a922b`
Apply after: `Commit 08`

## Goal

Add alert settings and a stable, secret-free generic webhook payload contract.

## Files

### `.env.example`

Replace this file with the complete post-commit content below.

````text
# GitHub personal access token: GitHub -> Settings -> Developer settings ->
# Personal access tokens -> Generate new token (scope: public_repo is enough)
RADAR_GITHUB_TOKEN=

RADAR_ANALYTICS_ROLLING_WINDOW=14
RADAR_ANALYTICS_BURST_Z=2.5
RADAR_ANALYTICS_BURST_MIN_DELTA=5
RADAR_ANALYTICS_BURST_MIN_DAYS=2
RADAR_ANALYTICS_HISTORY_DAYS=180

RADAR_SCHEDULER_ENABLED=false
RADAR_SCHEDULER_INTERVAL_HOURS=24

RADAR_ALERTS_ENABLED=true
RADAR_ALERT_WEBHOOK_URL=
RADAR_ALERT_WEBHOOK_TIMEOUT_SECONDS=10
````

### `src/alerts/webhook.py`

Create this file with the complete content below.

````python
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
````

### `src/config.py`

Replace this file with the complete post-commit content below.

````python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RADAR_",
        extra="ignore",
    )

    github_token: str = ""
    api_base_url: str = "https://api.github.com"
    request_timeout: float = 30.0
    user_agent: str = "github-radar/0.6"
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    database_url: str = "sqlite+aiosqlite:///./radar.db"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]

    analytics_rolling_window: int = 14
    analytics_burst_z: float = 2.5
    analytics_burst_min_delta: int = 5
    analytics_burst_min_days: int = 2
    analytics_history_days: int = 180

    scheduler_enabled: bool = False
    scheduler_interval_hours: int = 24

    alerts_enabled: bool = True
    alert_webhook_url: str = ""
    alert_webhook_timeout_seconds: float = 10.0


settings = Settings()
````

### `tests/test_alert_webhook.py`

Create this file with the complete content below.

````python
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
    payload = build_webhook_payload(_event(datetime(2026, 9, 16, 15, tzinfo=plus_three)))
    assert payload["created_at"] == "2026-09-16T12:00:00Z"
````

## Verify

```bash
pytest -q tests/test_alert_webhook.py
ruff check src/alerts/webhook.py src/config.py tests/test_alert_webhook.py
```

## Commit

```bash
git add -- \
  .env.example \
  src/alerts/webhook.py \
  src/config.py \
  tests/test_alert_webhook.py
git commit -m 'feat: configure optional alert webhook delivery'
```
