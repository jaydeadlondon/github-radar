from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
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


@app.command("init-db")
def init_db() -> None:
    async def _impl() -> None:
        from db.base import engine
        from db.models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        console.print("[green]Database initialized.[/green]")

    _run_async(_impl)


async def _store_repos(repos: list[RepoSummary]) -> int:
    from collector.store import save_repos
    from db.base import SessionFactory

    async with SessionFactory() as session:
        return await save_repos(session, repos)


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
    save: bool = typer.Option(False, "--save", help="Store results in the database."),
) -> None:
    async def _impl() -> None:
        async with GitHubClient() as client:
            repos = await client.search_repos("stars:>1000", per_page=limit)
        if save:
            saved = await _store_repos(repos)
            console.print(f"[green]Saved {saved} repositories.[/green]")
        _render_repos_table(repos, "Top repositories by stars")

    _run_async(_impl)


@app.command()
def search(
    query: str = typer.Option("", "--query", "-q", help="Free-text search query."),
    language: str = typer.Option(
        None, "--language", "-l", help="Filter by language, e.g. python."
    ),
    min_stars: int = typer.Option(
        50, "--min-stars", min=0, help="Minimum number of stars."
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        min=1,
        max=100,
        help="How many repositories to show.",
    ),
    save: bool = typer.Option(False, "--save", help="Store results in the database."),
) -> None:
    parts = [
        part
        for part in (
            query.strip(),
            language and f"language:{language}",
            min_stars and f"stars:>={min_stars}",
        )
        if part
    ]
    q = " ".join(parts)
    if not q:
        console.print(
            "[red]Error:[/red] give --query or at least one filter (--language/--min-stars)"
        )
        raise typer.Exit(2)

    async def _impl() -> None:
        async with GitHubClient() as client:
            repos = await client.search_repos(q, per_page=limit)
        if save:
            saved = await _store_repos(repos)
            console.print(f"[green]Saved {saved} repositories.[/green]")
        _render_repos_table(repos, "Search results")

    _run_async(_impl)


@app.command()
def repo(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Repository in owner/name format, e.g. psf/requests",
    ),
) -> None:
    if "/" not in full_name:
        console.print("[red]Error:[/red] expected owner/name format, e.g. psf/requests")
        raise typer.Exit(2)

    async def _impl() -> None:
        async with GitHubClient() as client:
            result = await client.get_repo(full_name)
        panel = Panel(
            f"[bold]{result.full_name}[/bold]\n\n{result.description or '—'}\n\n"
            f"Language: {result.language or '—'}\n"
            f"Stars: {result.stargazers_count}\n"
            f"Forks: {result.forks_count}\n"
            f"URL: {result.html_url}",
            title="Repository",
        )
        console.print(panel)

    _run_async(_impl)
