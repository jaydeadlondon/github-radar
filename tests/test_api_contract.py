from datetime import UTC, datetime, timedelta
from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary

NOW = datetime.now(UTC)
DAY = timedelta(days=1)


async def _seed_full_db(db_session) -> None:
    specs = [
        ("psf/requests", 500, "Python"),
        ("pallets/flask", 900, "Python"),
        ("golang/go", 700, "Go"),
        ("rust-lang/rust", 600, "Rust"),
    ]
    for index, (full_name, stars, lang) in enumerate(specs):
        repo = await upsert_repository(
            db_session,
            RepoSummary(
                id=index,
                full_name=full_name,
                description=f"About {full_name}",
                html_url=f"https://github.com/{full_name}",
                language=lang,
                stargazers_count=stars,
                forks_count=10 + index,
                created_at="2020-01-01T00:00:00Z",
                pushed_at="2024-01-01T00:00:00Z",
            ),
        )
        for offset, delta in [(3, 100), (2, 50), (1, 0)]:
            await create_snapshot(
                db_session,
                repo.id,
                stargazers=stars - delta,
                forks=10,
                observed_at=NOW - DAY * offset,
            )
    await db_session.commit()


async def test_repos_payload_contract(api_client, db_session):
    await _seed_full_db(db_session)
    response = await api_client.get("/api/v1/repos")
    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 4
    assert payload["offset"] == 0
    assert payload["limit"] == 20
    assert payload["next_offset"] is None
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) == 4

    item = payload["items"][0]
    assert isinstance(item["id"], int)
    assert isinstance(item["full_name"], str) and "/" in item["full_name"]
    assert isinstance(item["description"], str)
    assert item["html_url"].startswith("https://")
    assert item["language"] in {"Python", "Go", "Rust"}
    assert isinstance(item["stargazers_count"], int)
    assert isinstance(item["forks_count"], int)


async def test_pagination_consistency(api_client, db_session):
    await _seed_full_db(db_session)
    page1 = (await api_client.get("/api/v1/repos", params={"limit": 3})).json()
    page2 = (
        await api_client.get("/api/v1/repos", params={"limit": 3, "offset": 3})
    ).json()

    assert page1["total"] == page2["total"] == 4
    assert page1["next_offset"] == 3
    assert page2["next_offset"] is None
    assert len(page1["items"]) == 3
    assert len(page2["items"]) == 1
    first_ids = {item["id"] for item in page1["items"]}
    second_ids = {item["id"] for item in page2["items"]}
    assert first_ids.isdisjoint(second_ids)


async def test_detail_payload_contract(api_client, db_session):
    await _seed_full_db(db_session)
    response = await api_client.get("/api/v1/repos/pallets/flask")
    assert response.status_code == 200
    body = response.json()

    assert body["full_name"] == "pallets/flask"
    assert isinstance(body["created_at"], str)
    assert isinstance(body["updated_at"], str)
    snapshot = body["latest_snapshot"]
    assert snapshot["stargazers_count"] == 900
    assert snapshot["forks_count"] == 10
    assert isinstance(snapshot["observed_at"], str)


async def test_history_payload_contract(api_client, db_session):
    await _seed_full_db(db_session)
    response = await api_client.get("/api/v1/repos/golang/go/history")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 3
    for item in items:
        assert set(item) == {
            "stargazers_count",
            "forks_count",
            "open_issues_count",
            "observed_at",
        }
        assert isinstance(item["stargazers_count"], int)
    assert items[0]["stargazers_count"] <= items[-1]["stargazers_count"]


async def test_trends_payload_contract(api_client, db_session):
    await _seed_full_db(db_session)
    response = await api_client.get("/api/v1/trends", params={"window": 7})
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 4
    assert all(isinstance(item["stargazers_count"], int) for item in items)


async def test_languages_payload_contract(api_client, db_session):
    await _seed_full_db(db_session)
    response = await api_client.get("/api/v1/languages")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 3
    for item in items:
        assert set(item) == {"language", "repository_count", "total_stars"}
        assert isinstance(item["repository_count"], int)
        assert isinstance(item["total_stars"], int)
    totals = [item["total_stars"] for item in items]
    assert totals == sorted(totals, reverse=True)


async def test_error_shape_is_consistent(api_client):
    for path in ["/api/v1/repos/no/such", "/api/v1/nope", "/api/v1/trends/extra"]:
        response = await api_client.get(path)
        assert response.status_code == 404, path
        body = response.json()
        assert set(body) == {"detail", "code"}, path
        assert body["code"] == 404, path
        assert isinstance(body["detail"], str), path
