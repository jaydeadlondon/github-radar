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


async def _track(
    session,
    full_name: str,
    daily_stars: list[int],
    *,
    language: str = "Python",
    ends_days_ago: int = 0,
) -> None:
    repo = await upsert_repository(
        session, _summary(full_name, daily_stars[-1], language)
    )
    offset = len(daily_stars) - 1 + ends_days_ago
    for index, stars in enumerate(daily_stars):
        await create_snapshot(
            session,
            repo.id,
            stargazers=stars,
            forks=1,
            observed_at=NOW - DAY * (offset - index),
        )
    await session.commit()


async def test_series_endpoint_returns_daily_points(api_client, db_session):
    await _track(db_session, "psf/requests", [100, 110, 130])

    response = await api_client.get("/api/v1/analytics/series/psf/requests")
    assert response.status_code == 200
    body = response.json()

    assert body["repo"]["full_name"] == "psf/requests"
    assert body["repo"]["stars"] == 130
    assert body["smooth_window"] == 0
    assert [point["stars"] for point in body["points"]] == [100, 110, 130]
    assert [point["delta"] for point in body["points"]] == [0, 10, 20]
    assert all(point["stars_avg"] is None for point in body["points"])


async def test_series_endpoint_adds_moving_averages(api_client, db_session):
    await _track(db_session, "psf/requests", [100, 110, 130])

    response = await api_client.get(
        "/api/v1/analytics/series/psf/requests", params={"smooth": 2}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["smooth_window"] == 2
    assert [point["stars_avg"] for point in body["points"]] == [None, 105.0, 120.0]
    assert [point["delta_avg"] for point in body["points"]] == [None, 5.0, 15.0]


async def test_series_endpoint_validates_parameters(api_client, db_session):
    await _track(db_session, "psf/requests", [100, 110])

    assert (
        await api_client.get(
            "/api/v1/analytics/series/psf/requests", params={"days": 3}
        )
    ).status_code == 422
    assert (
        await api_client.get(
            "/api/v1/analytics/series/psf/requests", params={"smooth": 500}
        )
    ).status_code == 422


async def test_series_endpoint_unknown_repo(api_client):
    response = await api_client.get("/api/v1/analytics/series/ghost/repo")
    assert response.status_code == 404
    assert response.json() == {"detail": "repository ghost/repo not found", "code": 404}


async def test_compare_endpoint_aligns_two_repositories(api_client, db_session):
    await _track(db_session, "fast/repo", [100, 150, 200])
    await _track(db_session, "slow/repo", [1000, 1010, 1020])

    response = await api_client.get(
        "/api/v1/analytics/compare", params={"repos": "fast/repo,slow/repo"}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["mode"] == "absolute"
    assert body["window_days"] == 30
    assert len(body["days"]) == 3
    values = {item["full_name"]: item["values"] for item in body["series"]}
    assert values["fast/repo"] == [100.0, 150.0, 200.0]
    assert values["slow/repo"] == [1000.0, 1010.0, 1020.0]


async def test_compare_endpoint_supports_percent_mode(api_client, db_session):
    await _track(db_session, "fast/repo", [100, 150, 200])
    await _track(db_session, "slow/repo", [1000, 1010, 1020])

    response = await api_client.get(
        "/api/v1/analytics/compare",
        params={"repos": "fast/repo,slow/repo", "mode": "percent"},
    )
    assert response.status_code == 200
    values = {item["full_name"]: item["values"] for item in response.json()["series"]}

    assert values["fast/repo"] == [0.0, 50.0, 100.0]
    assert values["slow/repo"] == [0.0, 1.0, 2.0]


async def test_compare_endpoint_indexes_series_to_one_hundred(api_client, db_session):
    await _track(db_session, "fast/repo", [200, 260])

    response = await api_client.get(
        "/api/v1/analytics/compare",
        params={"repos": "fast/repo", "mode": "indexed"},
    )
    assert response.status_code == 200
    assert response.json()["series"][0]["values"] == [100.0, 130.0]


async def test_compare_endpoint_leaves_gaps_for_missing_days(api_client, db_session):
    await _track(db_session, "old/repo", [100, 110], ends_days_ago=2)
    await _track(db_session, "new/repo", [10, 20])

    response = await api_client.get(
        "/api/v1/analytics/compare", params={"repos": "old/repo,new/repo"}
    )
    assert response.status_code == 200
    values = {item["full_name"]: item["values"] for item in response.json()["series"]}

    assert values["old/repo"][-1] is None
    assert values["new/repo"][0] is None


async def test_compare_endpoint_reports_unknown_repositories(api_client, db_session):
    await _track(db_session, "fast/repo", [100, 150])

    response = await api_client.get(
        "/api/v1/analytics/compare", params={"repos": "fast/repo,ghost/repo"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "repositories not found: ghost/repo"


async def test_compare_endpoint_validates_the_request(api_client):
    too_many = await api_client.get(
        "/api/v1/analytics/compare",
        params={"repos": "a/b,c/d,e/f,g/h,i/j,k/l"},
    )
    assert too_many.status_code == 422
    assert too_many.json()["detail"] == "provide between 1 and 5 repositories"

    malformed = await api_client.get(
        "/api/v1/analytics/compare", params={"repos": "requests"}
    )
    assert malformed.status_code == 422

    bad_mode = await api_client.get(
        "/api/v1/analytics/compare", params={"repos": "a/b", "mode": "log"}
    )
    assert bad_mode.status_code == 422


async def test_leaderboard_filters_by_language(api_client, db_session):
    await _track(db_session, "py/repo", [100, 200, 300], language="Python")
    await _track(db_session, "go/repo", [100, 400, 700], language="Go")

    response = await api_client.get(
        "/api/v1/analytics/leaderboard", params={"language": "Python"}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert [item["full_name"] for item in body["items"]] == ["py/repo"]
    assert body["items"][0]["language"] == "Python"


async def test_leaderboard_language_filter_can_be_empty(api_client, db_session):
    await _track(db_session, "py/repo", [100, 200], language="Python")

    response = await api_client.get(
        "/api/v1/analytics/leaderboard", params={"language": "Rust"}
    )
    assert response.status_code == 200
    assert response.json()["items"] == []
