from datetime import UTC, datetime, timedelta

from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary

NOW = datetime.now(UTC)
DAY = timedelta(days=1)


async def _seed_analytics_db(db_session) -> None:
    """acme/rocket: +2/day ровно, всплеск +40/day пять дней (16..20 дней
    назад). acme/slow: +1/day ровно. По 60 дней истории."""
    rocket = await upsert_repository(
        db_session,
        RepoSummary(
            id=101,
            full_name="acme/rocket",
            description="Test rocket repo",
            html_url="https://github.com/acme/rocket",
            language="Python",
            stargazers_count=1120,
            forks_count=10,
            created_at="2020-01-01T00:00:00Z",
            pushed_at="2024-01-01T00:00:00Z",
        ),
    )
    slow = await upsert_repository(
        db_session,
        RepoSummary(
            id=102,
            full_name="acme/slow",
            description="Test slow repo",
            html_url="https://github.com/acme/slow",
            language="Go",
            stargazers_count=160,
            forks_count=5,
            created_at="2020-01-01T00:00:00Z",
            pushed_at="2024-01-01T00:00:00Z",
        ),
    )

    stars = 1000
    for days_ago in range(60, 0, -1):
        gained = 40 if 16 <= days_ago <= 20 else 2  # всплеск 16..20 дней назад
        stars += gained
        await create_snapshot(
            db_session,
            rocket.id,
            stargazers=stars,
            forks=10,
            observed_at=NOW - DAY * days_ago,
        )
    slow_stars = 100
    for days_ago in range(60, 0, -1):
        slow_stars += 1
        await create_snapshot(
            db_session,
            slow.id,
            stargazers=slow_stars,
            forks=5,
            observed_at=NOW - DAY * days_ago,
        )
    await db_session.commit()


async def test_velocity_endpoint_shape(api_client, db_session):
    await _seed_analytics_db(db_session)
    response = await api_client.get(
        "/api/v1/analytics/velocity/acme/rocket", params={"windows": "7,30"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["repo"]["full_name"] == "acme/rocket"
    assert [v["window_days"] for v in body["velocities"]] == [7, 30]
    assert body["velocities"][0]["stars_per_day"] == 2.0
    assert body["trend"]["n_points"] == 60


async def test_velocity_404_for_unknown_repo(api_client):
    response = await api_client.get("/api/v1/analytics/velocity/no/such")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"detail", "code"}


async def test_velocity_rejects_bad_windows(api_client, db_session):
    await _seed_analytics_db(db_session)
    response = await api_client.get(
        "/api/v1/analytics/velocity/acme/rocket", params={"windows": "0"}
    )
    assert response.status_code == 422
    response = await api_client.get(
        "/api/v1/analytics/velocity/acme/rocket",
        params={"windows": "1,2,3,4,5,6"},
    )
    assert response.status_code == 422


async def test_bursts_detected(api_client, db_session):
    await _seed_analytics_db(db_session)
    response = await api_client.get(
        "/api/v1/analytics/bursts/acme/rocket", params={"days": 90}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["duration_days"] == 5
    assert body["items"][0]["peak_delta"] == 40
    assert body["active_burst"] is False


async def test_bursts_404_for_unknown_repo(api_client):
    response = await api_client.get("/api/v1/analytics/bursts/no/such")
    assert response.status_code == 404


async def test_leaderboard_sorted_with_envelope(api_client, db_session):
    await _seed_analytics_db(db_session)
    response = await api_client.get(
        "/api/v1/analytics/leaderboard", params={"window": 7, "limit": 10}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {"total", "offset", "limit", "next_offset", "items"} <= set(body)
    assert body["items"][0]["full_name"] == "acme/rocket"
    assert body["items"][0]["rank"] == 1
    per_day = [item["stars_per_day"] for item in body["items"]]
    assert per_day == sorted(per_day, reverse=True)


async def test_leaderboard_rejects_bad_window(api_client):
    response = await api_client.get(
        "/api/v1/analytics/leaderboard", params={"window": 15}
    )
    assert response.status_code == 422


async def test_trends_items_have_stars_per_day(api_client, db_session):
    await _seed_analytics_db(db_session)
    response = await api_client.get("/api/v1/trends", params={"window": 7})
    assert response.status_code == 200
    items = response.json()
    assert items
    assert all(isinstance(item["stars_per_day"], (int, float)) for item in items)


async def test_repo_detail_has_analytics_fields(api_client, db_session):
    await _seed_analytics_db(db_session)
    response = await api_client.get("/api/v1/repos/acme/rocket")
    assert response.status_code == 200
    body = response.json()
    assert len(body["velocities"]) == 3  # окна 7/30/90
    assert body["active_burst"] is False
