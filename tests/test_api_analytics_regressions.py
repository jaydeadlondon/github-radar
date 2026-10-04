from datetime import UTC, datetime, timedelta

from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary

NOW = datetime.now(UTC)
DAY = timedelta(days=1)


def _summary(full_name: str, stars: int, language: str = "Python") -> RepoSummary:
    return RepoSummary(
        id=hash(full_name),
        full_name=full_name,
        description=f"About {full_name}",
        html_url=f"https://github.com/{full_name}",
        language=language,
        stargazers_count=stars,
        forks_count=1,
        created_at="2020-01-01T00:00:00Z",
        pushed_at="2024-01-01T00:00:00Z",
    )


async def _track(session, full_name: str, daily_stars: list[int]) -> None:
    repo = await upsert_repository(session, _summary(full_name, daily_stars[-1]))
    offset = len(daily_stars) - 1
    for index, stars in enumerate(daily_stars):
        await create_snapshot(
            session,
            repo.id,
            stargazers=stars,
            forks=1,
            observed_at=NOW - DAY * (offset - index),
        )
    await session.commit()


async def test_velocity_endpoint(api_client, db_session):
    await _track(db_session, "psf/requests", [100, 110, 120, 130, 140, 150, 160, 170])

    response = await api_client.get("/api/v1/analytics/velocity/psf/requests")
    assert response.status_code == 200
    body = response.json()

    assert body["repo"]["full_name"] == "psf/requests"
    assert body["repo"]["stars"] == 170
    assert [item["window_days"] for item in body["velocities"]] == [7, 30, 90]
    assert body["velocities"][0]["stars_per_day"] == 10.0
    assert body["trend"]["slope"] == 10.0
    assert body["trend"]["r_squared"] == 1.0


async def test_velocity_endpoint_accepts_custom_windows(api_client, db_session):
    await _track(db_session, "psf/requests", [100, 110, 120, 130])

    response = await api_client.get(
        "/api/v1/analytics/velocity/psf/requests", params={"windows": "3,7"}
    )
    assert response.status_code == 200
    assert [item["window_days"] for item in response.json()["velocities"]] == [3, 7]


async def test_velocity_endpoint_rejects_bad_windows(api_client, db_session):
    await _track(db_session, "psf/requests", [100, 110])

    bad = await api_client.get(
        "/api/v1/analytics/velocity/psf/requests", params={"windows": "week"}
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == 422

    too_many = await api_client.get(
        "/api/v1/analytics/velocity/psf/requests",
        params={"windows": "1,2,3,4,5,6"},
    )
    assert too_many.status_code == 422

    out_of_range = await api_client.get(
        "/api/v1/analytics/velocity/psf/requests", params={"windows": "400"}
    )
    assert out_of_range.status_code == 422


async def test_velocity_endpoint_unknown_repo(api_client):
    response = await api_client.get("/api/v1/analytics/velocity/ghost/repo")
    assert response.status_code == 404
    payload = response.json()
    assert payload["detail"] == "repository ghost/repo not found"
    assert payload["code"] == 404


async def test_bursts_endpoint_detects_a_spike(api_client, db_session):
    quiet = [100 + step for step in range(0, 20)]
    daily = [*quiet, quiet[-1] + 200, quiet[-1] + 400]
    await _track(db_session, "psf/requests", daily)

    response = await api_client.get("/api/v1/analytics/bursts/psf/requests")
    assert response.status_code == 200
    body = response.json()

    assert body["active_burst"] is True
    assert len(body["items"]) == 1
    event = body["items"][0]
    assert event["duration_days"] == 2
    assert event["peak_delta"] == 200
    assert event["total_gained"] == 400
    assert event["severity"] > 1


async def test_bursts_endpoint_is_empty_for_steady_growth(api_client, db_session):
    await _track(db_session, "psf/requests", [100 + step * 3 for step in range(0, 30)])

    response = await api_client.get("/api/v1/analytics/bursts/psf/requests")
    assert response.status_code == 200
    assert response.json() == {"items": [], "active_burst": False}


async def test_bursts_endpoint_unknown_repo(api_client):
    response = await api_client.get("/api/v1/analytics/bursts/ghost/repo")
    assert response.status_code == 404


async def test_leaderboard_ranks_by_stars_per_day(api_client, db_session):
    await _track(db_session, "fast/repo", [100, 200, 300, 400, 500, 600, 700, 800])
    await _track(db_session, "slow/repo", [100, 101, 102, 103, 104, 105, 106, 107])

    response = await api_client.get("/api/v1/analytics/leaderboard")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 2
    assert [item["rank"] for item in body["items"]] == [1, 2]
    assert [item["full_name"] for item in body["items"]] == ["fast/repo", "slow/repo"]
    assert body["items"][0]["owner"] == "fast"
    assert body["items"][0]["name"] == "repo"
    assert body["items"][0]["stars_per_day"] > body["items"][1]["stars_per_day"]
    assert body["items"][0]["stars"] == 800


async def test_leaderboard_paginates(api_client, db_session):
    await _track(db_session, "fast/repo", [100, 200, 300, 400, 500, 600, 700, 800])
    await _track(db_session, "slow/repo", [100, 101, 102, 103, 104, 105, 106, 107])

    first = await api_client.get("/api/v1/analytics/leaderboard", params={"limit": 1})
    assert first.status_code == 200
    assert first.json()["next_offset"] == 1
    assert [item["full_name"] for item in first.json()["items"]] == ["fast/repo"]

    second = await api_client.get(
        "/api/v1/analytics/leaderboard", params={"limit": 1, "offset": 1}
    )
    assert second.status_code == 200
    assert second.json()["next_offset"] is None
    assert [item["rank"] for item in second.json()["items"]] == [2]


async def test_leaderboard_rejects_unsupported_window(api_client):
    response = await api_client.get(
        "/api/v1/analytics/leaderboard", params={"window": 14}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "window must be one of 7, 30, 90"


async def test_leaderboard_is_empty_without_repositories(api_client):
    response = await api_client.get("/api/v1/analytics/leaderboard")
    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "offset": 0,
        "limit": 20,
        "next_offset": None,
        "items": [],
    }
