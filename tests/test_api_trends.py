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


async def test_history_endpoint(api_client, db_session):
    repo = await upsert_repository(db_session, _summary("psf/requests", 100))
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=10, observed_at=NOW - DAY
    )
    await create_snapshot(
        db_session, repo.id, stargazers=150, forks=12, observed_at=NOW
    )
    await db_session.commit()

    response = await api_client.get("/api/v1/repos/psf/requests/history")
    assert response.status_code == 200
    items = response.json()
    assert [s["stargazers_count"] for s in items] == [100, 150]
    assert items[0]["observed_at"] <= items[1]["observed_at"]


async def test_history_since_until(api_client, db_session):
    repo = await upsert_repository(db_session, _summary("psf/requests", 100))
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=10, observed_at=NOW - DAY * 5
    )
    await create_snapshot(
        db_session, repo.id, stargazers=110, forks=10, observed_at=NOW - DAY
    )
    await db_session.commit()

    response = await api_client.get(
        "/api/v1/repos/psf/requests/history",
        params={"since": (NOW - DAY * 2).isoformat()},
    )
    assert response.status_code == 200
    items = response.json()
    assert [s["stargazers_count"] for s in items] == [110]


async def test_history_invalid_range(api_client, db_session):
    repo = await upsert_repository(db_session, _summary("psf/requests", 100))
    await create_snapshot(
        db_session, repo.id, stargazers=100, forks=10, observed_at=NOW
    )
    await db_session.commit()

    response = await api_client.get(
        "/api/v1/repos/psf/requests/history",
        params={
            "since": (NOW + DAY).isoformat(),
            "until": (NOW - DAY).isoformat(),
        },
    )
    assert response.status_code == 422


async def test_history_not_found(api_client):
    response = await api_client.get("/api/v1/repos/unknown/repo/history")
    assert response.status_code == 404
    assert response.json()["code"] == 404


async def test_trends_ranks_by_growth(api_client, db_session):
    for full_name, delta in [("psf/requests", 50), ("pallets/flask", 10)]:
        repo = await upsert_repository(db_session, _summary(full_name, 100))
        await create_snapshot(
            db_session, repo.id, stargazers=100, forks=1, observed_at=NOW - DAY * 3
        )
        await create_snapshot(
            db_session,
            repo.id,
            stargazers=100 + delta,
            forks=1,
            observed_at=NOW - DAY,
        )
    await db_session.commit()

    response = await api_client.get("/api/v1/trends", params={"window": 7})
    assert response.status_code == 200
    names = [item["full_name"] for item in response.json()]
    assert names == ["psf/requests", "pallets/flask"]


async def test_trends_invalid_window(api_client):
    response = await api_client.get("/api/v1/trends", params={"window": 15})
    assert response.status_code == 422


async def test_languages_aggregate(api_client, db_session):
    now = datetime.now(UTC)
    for full_name, stars, lang in [
        ("psf/requests", 500, "Python"),
        ("pallets/flask", 700, "Python"),
        ("golang/go", 800, "Go"),
    ]:
        repo = await upsert_repository(db_session, _summary(full_name, stars, lang))
        await create_snapshot(
            db_session, repo.id, stargazers=stars, forks=1, observed_at=now
        )
    await db_session.commit()

    response = await api_client.get("/api/v1/languages")
    assert response.status_code == 200
    by_lang = {item["language"]: item for item in response.json()}
    assert response.json()[0]["language"] == "Python"
    assert by_lang["Python"]["repository_count"] == 2
    assert by_lang["Python"]["total_stars"] == 1200
    assert by_lang["Go"]["total_stars"] == 800


async def test_health_ok(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


async def test_root_stub(api_client):
    response = await api_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "GitHub Radar" in response.text
    docs = await api_client.get("/docs")
    assert docs.status_code == 200


async def test_unknown_route_returns_error_shape(api_client):
    response = await api_client.get("/api/v1/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 404
    assert "detail" in body


async def test_error_shape_has_request_id(api_client):
    response = await api_client.get("/api/v1/repos/no/such-repo")
    assert response.headers.get("X-Request-ID")
