from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

import collector.pipeline as pipeline
from alerts import BURST_STARTED, STARS_REACHED, VELOCITY_ABOVE, RuleSpec
from alerts.runner import evaluate_rules
from db.alerts import create_rule, list_events
from db.models import RepoSnapshot
from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary


def _summary(stars: int = 100) -> RepoSummary:
    return RepoSummary(
        id=1,
        full_name="acme/rocket",
        description="Fast",
        html_url="https://github.com/acme/rocket",
        language="Python",
        stargazers_count=stars,
        forks_count=1,
    )


async def _seed_history(db_session):
    repo = await upsert_repository(db_session, _summary())
    now = datetime.now(UTC).replace(microsecond=0)
    stars = 100
    values = [stars]
    for delta in [1] * 14 + [100, 120]:
        stars += delta
        values.append(stars)
    for index, value in enumerate(values):
        await create_snapshot(
            db_session,
            repo.id,
            stargazers=value,
            forks=1,
            observed_at=now - timedelta(days=len(values) - index - 1),
        )
    return repo, now, stars


async def test_evaluate_rules_creates_and_delivers_all_alert_types(db_session) -> None:
    repo, now, latest_stars = await _seed_history(db_session)
    await create_rule(
        db_session,
        repo,
        RuleSpec(kind=STARS_REACHED, threshold=300),
    )
    await create_rule(
        db_session,
        repo,
        RuleSpec(kind=VELOCITY_ABOVE, threshold=10, window_days=7),
    )
    await create_rule(db_session, repo, RuleSpec(kind=BURST_STARTED))
    await db_session.commit()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    events = await evaluate_rules(
        db_session,
        [repo.id],
        evaluated_at=now,
        webhook_url="https://hooks.example.test/radar",
        transport=httpx.MockTransport(handler),
    )
    await db_session.commit()

    assert latest_stars >= 300
    assert {event.kind for event in events} == {
        STARS_REACHED,
        VELOCITY_ABOVE,
        BURST_STARTED,
    }
    assert all(event.delivery_status == "sent" for event in events)
    assert len(requests) == 3

    repeated = await evaluate_rules(
        db_session,
        [repo.id],
        evaluated_at=now,
        webhook_url="",
    )
    await db_session.commit()
    assert repeated == []
    assert (await list_events(db_session))[1] == 3


async def test_webhook_failure_keeps_persisted_event(db_session) -> None:
    repo, now, _latest = await _seed_history(db_session)
    await create_rule(
        db_session,
        repo,
        RuleSpec(kind=STARS_REACHED, threshold=200),
    )
    await db_session.commit()

    event = (
        await evaluate_rules(
            db_session,
            [repo.id],
            evaluated_at=now,
            webhook_url="https://hooks.example.test/fail",
            transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        )
    )[0]
    await db_session.commit()

    assert event.delivery_status == "failed"
    assert event.delivery_error == "HTTP 500"
    stored, total = await list_events(db_session)
    assert total == 1
    assert stored[0].id == event.id


class FakeGitHubClient:
    async def __aenter__(self) -> FakeGitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_repo(self, _full_name: str) -> RepoSummary:
        return _summary(stars=500)


async def test_snapshot_passes_updated_repository_ids_to_alerts(
    db_session, monkeypatch
) -> None:
    repo = await upsert_repository(db_session, _summary())
    await db_session.commit()
    received: list[int] = []

    async def fake_evaluate(repo_ids) -> int:
        received.extend(repo_ids)
        return 0

    monkeypatch.setattr(pipeline, "GitHubClient", lambda: FakeGitHubClient())
    monkeypatch.setattr(pipeline, "run_alert_evaluation", fake_evaluate)

    saved = await pipeline.run_snapshot()

    assert saved == 1
    assert received == [repo.id]


async def test_alert_failure_does_not_roll_back_snapshot(
    db_session, monkeypatch, caplog
) -> None:
    await upsert_repository(db_session, _summary())
    await db_session.commit()

    async def fail_alerts(_repo_ids) -> int:
        raise RuntimeError("delivery infrastructure unavailable")

    monkeypatch.setattr(pipeline, "GitHubClient", lambda: FakeGitHubClient())
    monkeypatch.setattr(pipeline, "run_alert_evaluation", fail_alerts)

    saved = await pipeline.run_snapshot()

    assert saved == 1
    count = await db_session.scalar(select(func.count(RepoSnapshot.id)))
    assert count == 1
    assert "alert evaluation failed" in caplog.text
