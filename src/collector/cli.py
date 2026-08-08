from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
import typer
from rich.console import Console
from rich.table import Table
from github.client import GitHubClient
from github.errors import GitHubError
from github.models import RepoSummary
from version import __version__

app = typer.Typer(
    name="radar",
    help="GitHub Radar — track rising stars on GitHub.",
    no_args_is_help=True,
)
console = Console()


def _run_async(fn: Callable[[], Awaitable[None]]) -> None:
    async def _wrapper() -> None:
        try:
            await fn()
        except GitHubError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc

    asyncio.run(_wrapper())


@app.command()
def version() -> None:
    console.print(f"github-radar {__version__}")


def _render_repos_table(repos: list[RepoSummary], title: str) -> None:
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Repository")
    table.add_column("Language")
    table.add_column("Stars", justify="right")
    table.add_column("Forks", justify="right")
    for index, repo in enumerate(repos, start=1):
        table.add_row(
            str(index),
            repo.full_name,
            repo.language or "—",
            f"{repo.stargazers_count:,}",
            f"{repo.forks_count:,}",
        )
    console.print(table)


@app.command()
def top(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        min=1,
        max=100,
        help="How many repositories to show.",
    ),
) -> None:
    async def _impl() -> None:
        async with GitHubClient() as client:
            repos = await client.search_repos("stars:>1000", per_page=limit)
        _render_repos_table(repos, "Top repositories by stars")

    _run_async(_impl)
