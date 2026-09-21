from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

import collector.pipeline as pipeline
from db.models import RepoSnapshot
from db.repositories import create_snapshot, get_repository_by_name, upsert_repository
from github.errors import ApiError
from github.models import RepoSummary


def _summary(full_name: str = "acme/rocket", stars: int = 100) -> RepoSummary:
    return RepoSummary(
        id=hash(full_name),
        full_name=full_name,
        description="A rocket",
        html_url=f"https://github.com/{full_name}",
        language="Python",
        stargazers_count=stars,
        forks_count=2,
        created_at="2020-01-01T00:00:00Z",
        pushed_at="2026-01-01T00:00:00Z",
    )


async def test_tracking_status_and_untrack_keep_history(api_client, db_session):
    repo = await upsert_repository(db_session, _summary())
    await create_snapshot(
        db_session,
        repo.id,
        stargazers=100,
        forks=2,
        observed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await db_session.commit()

    status = await api_client.get("/api/v1/repos/acme/rocket/status")
    assert status.status_code == 200
    assert status.json()["status"] == "healthy"
    assert status.json()["snapshot_count"] == 1

    removed = await api_client.delete("/api/v1/repos/acme/rocket/track")
    assert removed.status_code == 200
    assert removed.json()["status"] == "untracked"

    assert (await api_client.get("/api/v1/repos")).json()["total"] == 0
    known = await api_client.get("/api/v1/repos", params={"tracking": "all"})
    assert known.json()["total"] == 1
    history = await db_session.scalar(select(func.count(RepoSnapshot.id)))
    assert history == 1


async def test_pause_and_resume_api_accept_tracking_field_aliases(api_client, db_session):
    await upsert_repository(db_session, _summary())
    await db_session.commit()

    paused = await api_client.patch(
        "/api/v1/repos/acme/rocket/tracking",
        json={"tracking_paused": True, "tracking_label": "core"},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert paused.json()["tracking_label"] == "core"

    resumed = await api_client.patch("/api/v1/repos/acme/rocket/tracking", json={"paused": False})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "stale"


class _FakeClient:
    def __init__(self, result: RepoSummary | Exception):
        self.result = result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object):
        return None

    async def get_repo(self, _full_name: str):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_snapshot_skips_paused_and_records_sanitized_failure(db_session, monkeypatch):
    repo = await upsert_repository(db_session, _summary())
    repo.tracking_paused = True
    await db_session.commit()
    monkeypatch.setattr(pipeline, "GitHubClient", lambda: _FakeClient(_summary(stars=200)))
    assert await pipeline.run_snapshot() == 0
    assert await db_session.scalar(select(func.count(RepoSnapshot.id))) == 0

    repo.tracking_paused = False
    await db_session.commit()
    monkeypatch.setattr(
        pipeline,
        "GitHubClient",
        lambda: _FakeClient(ApiError("Authorization: Bearer very-secret-token", 500)),
    )
    assert await pipeline.run_snapshot() == 0
    await db_session.refresh(repo)
    assert repo.last_snapshot_error is not None
    assert "very-secret" not in repo.last_snapshot_error
    assert "redacted" in repo.last_snapshot_error


async def test_track_existing_repository_endpoint_is_idempotent(api_client, db_session):
    await upsert_repository(db_session, _summary())
    await db_session.commit()

    first = await api_client.post("/api/v1/repos/acme/rocket/track", json={"label": "important"})
    second = await api_client.post("/api/v1/repos/acme/rocket/track", json={"label": "important"})
    assert first.status_code == second.status_code == 200
    assert second.json()["tracking_enabled"] is True
    assert second.json()["tracking_label"] == "important"
    assert await get_repository_by_name(db_session, "acme/rocket") is not None
