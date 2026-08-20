from datetime import UTC, datetime, timedelta
from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary

BASE = "/api/v1/repos"


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


async def _seed(db_session, repos: list[RepoSummary]) -> None:
    now = datetime.now(UTC)
    for index, summary in enumerate(repos):
        repo = await upsert_repository(db_session, summary)
        await create_snapshot(
            db_session,
            repo.id,
            stargazers=summary.stargazers_count,
            forks=summary.forks_count,
            observed_at=now - timedelta(hours=index),
        )
    await db_session.commit()


async def test_list_repos_empty(api_client):
    response = await api_client.get(BASE)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["items"] == []
    assert payload["next_offset"] is None


async def test_list_repos_with_data(api_client, db_session):
    await _seed(
        db_session,
        [_summary("psf/requests", 500), _summary("pallets/flask", 900)],
    )

    response = await api_client.get(BASE)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    names = [item["full_name"] for item in payload["items"]]
    # Sorted by stars desc: flask first.
    assert names == ["pallets/flask", "psf/requests"]
    assert payload["items"][0]["stargazers_count"] == 900


async def test_list_repos_language_filter(api_client, db_session):
    await _seed(
        db_session,
        [
            _summary("psf/requests", 500, language="Python"),
            _summary("golang/go", 700, language="Go"),
        ],
    )

    response = await api_client.get(BASE, params={"language": "Go"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["full_name"] == "golang/go"


async def test_list_repos_pagination(api_client, db_session):
    await _seed(
        db_session,
        [_summary(f"owner/repo{i}", 100 - i) for i in range(3)],
    )

    response = await api_client.get(BASE, params={"limit": 2, "offset": 0})
    payload = response.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert payload["next_offset"] == 2

    page2 = await api_client.get(BASE, params={"limit": 2, "offset": 2})
    assert len(page2.json()["items"]) == 1
    assert page2.json()["next_offset"] is None


async def test_list_repos_invalid_sort(api_client):
    response = await api_client.get(BASE, params={"sort": "bogus"})
    assert response.status_code == 422


async def test_get_repo_detail(api_client, db_session):
    await _seed(db_session, [_summary("psf/requests", 500)])

    response = await api_client.get(f"{BASE}/psf/requests")
    assert response.status_code == 200
    payload = response.json()
    assert payload["full_name"] == "psf/requests"
    assert payload["latest_snapshot"]["stargazers_count"] == 500


async def test_get_repo_404(api_client):
    response = await api_client.get(f"{BASE}/no/such-repo")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 404
    assert "not tracked" in body["detail"]


async def test_get_repo_invalid_name_format(api_client):
    response = await api_client.get(f"{BASE}/not-a-slug")
    assert response.status_code == 404
