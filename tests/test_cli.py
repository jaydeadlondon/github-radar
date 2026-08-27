from __future__ import annotations

from typer.testing import CliRunner

import collector.cli as cli
from collector.cli import app
from github.errors import NotFoundError
from github.models import RepoSummary

runner = CliRunner()

REPO = RepoSummary(
    id=1,
    full_name="psf/requests",
    description="A simple HTTP library",
    html_url="https://github.com/psf/requests",
    language="Python",
    stargazers_count=100,
    forks_count=9,
)


class FakeClient:
    def __init__(
        self,
        repos: list[RepoSummary] | None = None,
        repo: RepoSummary | None = None,
    ) -> None:
        self._repos = repos or []
        self._repo = repo

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search_repos(
        self,
        query: str,
        sort: str = "stars",
        order: str = "desc",
        per_page: int = 30,
    ):
        return self._repos

    async def get_repo(self, full_name: str) -> RepoSummary:
        if self._repo is None:
            raise NotFoundError(f"resource not found: {full_name}", 404)
        return self._repo


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "github-radar" in result.output


def test_top_renders_repos(monkeypatch) -> None:
    fake = FakeClient(repos=[REPO])
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: fake)
    result = runner.invoke(app, ["top", "--limit", "1"])
    assert result.exit_code == 0
    assert "psf/requests" in result.output
    assert "Python" in result.output


def test_top_prints_error_and_exits(monkeypatch) -> None:
    class FailingClient:
        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def search_repos(
            self,
            query: str,
            sort: str = "stars",
            order: str = "desc",
            per_page: int = 30,
        ):
            raise NotFoundError("resource not found", 404)

    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: FailingClient())
    result = runner.invoke(app, ["top"])
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_search_renders_results(monkeypatch) -> None:
    fake = FakeClient(repos=[REPO])
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: fake)
    result = runner.invoke(app, ["search", "--language", "python"])
    assert result.exit_code == 0
    assert "psf/requests" in result.output


def test_search_requires_some_filter() -> None:
    result = runner.invoke(app, ["search", "--min-stars", "0"])
    assert result.exit_code == 2
    assert "Error:" in result.output


def test_repo_shows_details(monkeypatch) -> None:
    fake = FakeClient(repo=REPO)
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: fake)
    result = runner.invoke(app, ["repo", "psf/requests"])
    assert result.exit_code == 0
    assert "psf/requests" in result.output
    assert "A simple HTTP library" in result.output


def test_repo_requires_owner_name() -> None:
    result = runner.invoke(app, ["repo", "not-a-slug"])
    assert result.exit_code == 2
    assert "Error:" in result.output
