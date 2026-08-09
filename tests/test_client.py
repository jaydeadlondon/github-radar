import asyncio
import httpx
import pytest
from github.errors import NotFoundError
from github.models import RepoSummary

REPO_JSON = {
    "id": 1,
    "full_name": "psf/requests",
    "description": "A simple HTTP library",
    "html_url": "https://github.com/psf/requests",
    "language": "Python",
    "stargazers_count": 62000,
    "forks_count": 9000,
    "created_at": "2011-02-13T18:44:23Z",
    "pushed_at": "2024-01-01T00:00:00Z",
}

SEARCH_JSON = {"total_count": 1, "incomplete_results": False, "items": [REPO_JSON]}


def test_search_repos_builds_url_and_headers(client_factory):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["accept"] = request.headers.get("Accept")
        captured["user_agent"] = request.headers.get("User-Agent")
        return httpx.Response(200, json=SEARCH_JSON)

    client = client_factory(handler)
    repos = asyncio.run(client.search_repos("language:python", per_page=10))

    assert captured["url"].startswith("https://api.github.com/search/repositories")
    assert "q=language" in captured["url"]
    assert "sort=stars" in captured["url"]
    assert "per_page=10" in captured["url"]
    assert captured["auth"] == "Bearer test-token"
    assert captured["accept"] == "application/vnd.github+json"
    assert "github-radar" in captured["user_agent"]
    assert repos == [RepoSummary.model_validate(REPO_JSON)]


def test_get_repo_parses_summary(client_factory):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=REPO_JSON)

    client = client_factory(handler)
    repo = asyncio.run(client.get_repo("psf/requests"))

    assert repo.full_name == "psf/requests"
    assert repo.stargazers_count == 62000
    assert repo.language == "Python"


def test_get_repo_raises_not_found(client_factory):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = client_factory(handler)
    with pytest.raises(NotFoundError):
        asyncio.run(client.get_repo("no/such-repo"))
