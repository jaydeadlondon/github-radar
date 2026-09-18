from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary


async def _seed(db_session):
    repo = await upsert_repository(
        db_session,
        RepoSummary(
            id=1,
            full_name="acme/export",
            html_url="https://github.com/acme/export",
            stargazers_count=120,
            forks_count=2,
        ),
    )
    now = datetime.now(UTC)
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=1, observed_at=now - timedelta(days=1)
    )
    await create_snapshot(db_session, repo.id, stargazers=120, forks=2, observed_at=now)
    await db_session.commit()


async def test_series_csv_has_stable_header(api_client, db_session):
    await _seed(db_session)
    response = await api_client.get("/api/v1/analytics/series/acme/export?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "day,stars,delta"
    assert "Content-Disposition" in response.headers


async def test_leaderboard_csv_has_stable_header(api_client, db_session):
    await _seed(db_session)
    response = await api_client.get(
        "/api/v1/analytics/leaderboard", params={"window": 7, "format": "csv"}
    )
    assert response.status_code == 200
    assert response.text.splitlines()[0] == (
        "rank,owner,name,full_name,language,stars,stars_per_day,stars_gained"
    )


async def test_repository_json_export_payload_shape(api_client, db_session):
    await _seed(db_session)
    response = await api_client.get("/api/v1/analytics/series/acme/export")
    assert response.status_code == 200
    body = response.json()
    assert {"repo", "smooth_window", "points"} <= set(body)
    assert body["points"][-1]["stars"] == 120
