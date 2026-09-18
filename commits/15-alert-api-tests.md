# Commit 15 — test: cover alert API contracts and validation

Reference implementation commit: `a2fdf2c15ff6d4daf859dc2a2aabdd60609a6901`
Apply after: `Commit 14`

## Goal

Verify alert API contracts, validation, pagination, lifecycle behavior, retained events, and webhook URL secrecy.

## Files

### `tests/test_api_alerts.py`

Create this file with the complete content below.

````python
from __future__ import annotations

from alerts import BURST_STARTED, STARS_REACHED, AlertCandidate, RuleSpec
from config import settings
from db.alerts import create_event, create_rule
from db.base import SessionFactory
from db.repositories import upsert_repository
from github.models import RepoSummary

RULE_KEYS = {
    "id",
    "repository",
    "kind",
    "threshold",
    "window_days",
    "enabled",
    "last_value",
    "last_evaluated_at",
    "created_at",
    "updated_at",
}
EVENT_KEYS = {
    "id",
    "rule_id",
    "repository",
    "kind",
    "title",
    "message",
    "current_value",
    "threshold",
    "acknowledged_at",
    "delivery_status",
    "delivery_error",
    "created_at",
}


def _summary(full_name: str = "acme/rocket") -> RepoSummary:
    return RepoSummary(
        id=1,
        full_name=full_name,
        description="Fast",
        html_url=f"https://github.com/{full_name}",
        language="Python",
        stargazers_count=100,
        forks_count=1,
    )


async def _seed_repo(full_name: str = "acme/rocket") -> None:
    async with SessionFactory() as session:
        await upsert_repository(session, _summary(full_name))
        await session.commit()


async def _post_rule(api_client, **overrides):
    body = {
        "repository": "acme/rocket",
        "kind": "velocity_above",
        "threshold": 25,
        "window_days": 7,
        **overrides,
    }
    return await api_client.post("/api/v1/alerts/rules", json=body)


async def _seed_event(fingerprint: str = "milestone:1000") -> int:
    async with SessionFactory() as session:
        repo = await upsert_repository(session, _summary())
        rule = await create_rule(
            session,
            repo,
            RuleSpec(kind=STARS_REACHED, threshold=1000),
        )
        event = await create_event(
            session,
            rule,
            AlertCandidate(
                kind=STARS_REACHED,
                fingerprint=fingerprint,
                title="Star milestone reached",
                message="acme/rocket reached 1,000 stars",
                current_value=1001,
                threshold=1000,
            ),
        )
        assert event is not None
        await session.commit()
        return event.id


async def test_create_all_rule_types_and_exact_contract(api_client) -> None:
    await _seed_repo()

    velocity = await _post_rule(api_client)
    burst = await _post_rule(
        api_client,
        kind="burst_started",
        threshold=None,
        window_days=None,
    )
    milestone = await _post_rule(
        api_client,
        kind="stars_reached",
        threshold=10000,
        window_days=None,
    )

    assert velocity.status_code == burst.status_code == milestone.status_code == 201
    assert set(velocity.json()) == RULE_KEYS
    assert velocity.json()["window_days"] == 7
    assert burst.json()["kind"] == BURST_STARTED
    assert milestone.json()["threshold"] == 10000


async def test_rule_creation_requires_tracked_repository(api_client) -> None:
    response = await _post_rule(api_client)
    assert response.status_code == 404
    assert response.json() == {
        "detail": "repository acme/rocket not found",
        "code": 404,
    }


async def test_rule_condition_combinations_are_validated(api_client) -> None:
    await _seed_repo()

    burst = await _post_rule(
        api_client,
        kind="burst_started",
        threshold=1,
        window_days=None,
    )
    velocity = await _post_rule(api_client, window_days=14)
    milestone = await _post_rule(
        api_client,
        kind="stars_reached",
        threshold=99.5,
        window_days=None,
    )

    assert burst.status_code == velocity.status_code == milestone.status_code == 422
    assert "do not accept" in burst.json()["detail"]
    assert "one of 7, 30, 90" in velocity.json()["detail"]
    assert "whole number" in milestone.json()["detail"]


async def test_rule_list_filters_and_paginates(api_client) -> None:
    await _seed_repo()
    first = await _post_rule(api_client)
    await _post_rule(api_client, threshold=50, enabled=False)

    response = await api_client.get(
        "/api/v1/alerts/rules?repository=acme/rocket&enabled=true&limit=1"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["next_offset"] is None
    assert response.json()["items"][0]["id"] == first.json()["id"]


async def test_get_patch_and_delete_rule(api_client) -> None:
    await _seed_repo()
    created = (await _post_rule(api_client)).json()
    rule_id = created["id"]

    fetched = await api_client.get(f"/api/v1/alerts/rules/{rule_id}")
    patched = await api_client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={
            "kind": "burst_started",
            "threshold": None,
            "window_days": None,
            "enabled": False,
        },
    )
    deleted = await api_client.delete(f"/api/v1/alerts/rules/{rule_id}")
    missing = await api_client.get(f"/api/v1/alerts/rules/{rule_id}")

    assert fetched.status_code == 200
    assert patched.status_code == 200
    assert patched.json()["kind"] == BURST_STARTED
    assert patched.json()["threshold"] is None
    assert patched.json()["enabled"] is False
    assert deleted.status_code == 204 and not deleted.content
    assert missing.status_code == 404


async def test_rule_patch_resets_evaluation_state(api_client) -> None:
    await _seed_repo()
    rule_id = (await _post_rule(api_client)).json()["id"]
    async with SessionFactory() as session:
        from db.alerts import get_rule

        rule = await get_rule(session, rule_id)
        assert rule is not None
        rule.last_value = 30
        await session.commit()

    response = await api_client.patch(
        f"/api/v1/alerts/rules/{rule_id}", json={"threshold": 40}
    )

    assert response.status_code == 200
    assert response.json()["threshold"] == 40
    assert response.json()["last_value"] is None
    assert response.json()["last_evaluated_at"] is None


async def test_event_list_and_exact_contract(api_client) -> None:
    event_id = await _seed_event()

    response = await api_client.get(
        "/api/v1/alerts/events?repository=acme/rocket&kind=stars_reached&acknowledged=false"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == event_id
    assert set(payload["items"][0]) == EVENT_KEYS


async def test_acknowledge_event_and_clear_it_again(api_client) -> None:
    event_id = await _seed_event()

    acknowledged = await api_client.patch(
        f"/api/v1/alerts/events/{event_id}", json={"acknowledged": True}
    )
    cleared = await api_client.patch(
        f"/api/v1/alerts/events/{event_id}", json={"acknowledged": False}
    )

    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_at"] is not None
    assert cleared.status_code == 200
    assert cleared.json()["acknowledged_at"] is None


async def test_acknowledge_all_and_summary(api_client) -> None:
    await _seed_event("one")
    await _seed_event("two")

    before = await api_client.get("/api/v1/alerts/summary")
    changed = await api_client.post("/api/v1/alerts/events/acknowledge-all")
    after = await api_client.get("/api/v1/alerts/summary")

    assert before.json()["active_rules"] == 2
    assert before.json()["unread_events"] == 2
    assert before.json()["last_event_at"] is not None
    assert changed.json() == {"acknowledged": 2}
    assert after.json()["unread_events"] == 0


async def test_unknown_rule_and_event_use_existing_error_shape(api_client) -> None:
    rule = await api_client.get("/api/v1/alerts/rules/999")
    event = await api_client.get("/api/v1/alerts/events/999")
    assert rule.status_code == event.status_code == 404
    assert rule.json() == {"detail": "alert rule 999 not found", "code": 404}
    assert event.json() == {"detail": "alert event 999 not found", "code": 404}


async def test_rule_and_event_outputs_never_expose_webhook_url(
    api_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "alert_webhook_url", "https://user:secret@example.test")
    await _seed_repo()
    rule = await _post_rule(api_client)
    await _seed_event()
    events = await api_client.get("/api/v1/alerts/events")

    serialized = f"{rule.text}\n{events.text}"
    assert "secret" not in serialized
    assert "webhook_url" not in serialized


def test_alert_routes_are_present_in_openapi() -> None:
    from api.app import create_app

    paths = create_app().openapi()["paths"]
    assert {
        "/api/v1/alerts/rules",
        "/api/v1/alerts/rules/{rule_id}",
        "/api/v1/alerts/events",
        "/api/v1/alerts/events/{event_id}",
        "/api/v1/alerts/events/acknowledge-all",
        "/api/v1/alerts/summary",
    } <= set(paths)
````

## Verify

```bash
pytest -q tests/test_api_alerts.py tests/test_api_contract.py
```

## Commit

```bash
git add -- tests/test_api_alerts.py
git commit -m 'test: cover alert API contracts and validation'
```
