from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC

import typer
from rich.console import Console
from rich.panel import Panel
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
alerts_app = typer.Typer(help="Manage alert rules and the alert inbox.", no_args_is_help=True)
app.add_typer(alerts_app, name="alerts")


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


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes."),
    with_scheduler: bool = typer.Option(
        False, "--with-scheduler", help="Run the background snapshot scheduler."
    ),
) -> None:
    def _impl() -> None:
        import uvicorn

        from api.app import create_app
        from config import settings

        if with_scheduler:
            settings.scheduler_enabled = True

        uvicorn.run(create_app(), host=host, port=port, reload=reload)

    _impl()


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
def history(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Tracked repository in owner/name format, e.g. psf/requests.",
    ),
    days: int = typer.Option(30, "--days", min=1, help="How many days back to show."),
) -> None:
    if "/" not in full_name:
        console.print("[red]Error:[/red] expected owner/name format, e.g. psf/requests")
        raise typer.Exit(2)

    async def _impl() -> None:
        from datetime import datetime, timedelta

        from db.base import SessionFactory
        from db.repositories import get_history, get_repository_by_name

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                console.print(f"[red]Repository not tracked:[/red] {full_name}")
                raise typer.Exit(1)
            since = datetime.now(UTC) - timedelta(days=days)
            snapshots = await get_history(session, repo.id, since=since)

        if not snapshots:
            console.print(
                f"[yellow]No snapshots for {full_name} in the last {days} days.[/yellow]"
            )
            return

        table = Table(title=f"History: {full_name} (last {days} days)")
        table.add_column("Observed at")
        table.add_column("Stars", justify="right")
        table.add_column("Forks", justify="right")
        table.add_column("Δ stars", justify="right")
        previous: int | None = None
        for snap in snapshots:
            delta = snap.stargazers_count - previous if previous is not None else 0
            table.add_row(
                snap.observed_at.strftime("%Y-%m-%d %H:%M"),
                f"{snap.stargazers_count:,}",
                f"{snap.forks_count:,}",
                f"{delta:+d}",
            )
            previous = snap.stargazers_count
        console.print(table)

    _run_async(_impl)


@app.command()
def snapshot() -> None:
    async def _impl() -> None:
        from collector.pipeline import run_snapshot

        saved = await run_snapshot()
        if saved:
            console.print(
                f"[green]Snapshot complete: {saved} repository(-ies) updated.[/green]"
            )
        else:
            console.print(
                "[yellow]No tracked repositories yet. Try `radar top --save` first.[/yellow]"
            )

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


@app.command()
def velocity(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Tracked repository in owner/name format, e.g. psf/requests.",
    ),
    history_days: int = typer.Option(
        180, "--history-days", min=7, help="How many days of history to use."
    ),
) -> None:
    if "/" not in full_name:
        console.print("[red]Error:[/red] expected owner/name format, e.g. psf/requests")
        raise typer.Exit(2)

    async def _impl() -> None:
        from analytics import service
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                console.print(f"[red]Repository not tracked:[/red] {full_name}")
                raise typer.Exit(1)
            velocities, trend, _stars = await service.repo_velocity(
                session, repo.id, windows=(7, 30, 90), history_days=history_days
            )

        if not velocities:
            console.print(
                f"[yellow]Not enough snapshot history for {full_name}.[/yellow]"
            )
            return

        table = Table(title=f"Velocity: {full_name}")
        table.add_column("Window")
        table.add_column("Stars/day", justify="right")
        table.add_column("Gained", justify="right")
        for v in velocities:
            table.add_row(
                f"{v.window_days}d", f"{v.stars_per_day:.2f}", str(v.stars_gained)
            )
        console.print(table)
        if trend is not None:
            console.print(
                f"OLS trend: [bold]{trend.slope:.2f}[/bold] stars/day, "
                f"R² {trend.r_squared:.3f} ({trend.n_points} points)"
            )

    _run_async(_impl)


@app.command()
def bursts(
    full_name: str = typer.Argument(
        ...,
        metavar="owner/name",
        help="Tracked repository in owner/name format, e.g. psf/requests.",
    ),
    days: int = typer.Option(90, "--days", min=7, help="How many days back to scan."),
) -> None:
    if "/" not in full_name:
        console.print("[red]Error:[/red] expected owner/name format, e.g. psf/requests")
        raise typer.Exit(2)

    async def _impl() -> None:
        from analytics import service
        from config import settings
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                console.print(f"[red]Repository not tracked:[/red] {full_name}")
                raise typer.Exit(1)
            events, active = await service.repo_bursts(
                session,
                repo.id,
                history_days=days,
                rolling_window=settings.analytics_rolling_window,
                z_threshold=settings.analytics_burst_z,
                min_delta=settings.analytics_burst_min_delta,
                min_duration=settings.analytics_burst_min_days,
            )

        if not events:
            console.print(
                f"No bursts detected for {full_name} in the last {days} days."
            )
            return

        table = Table(title=f"Bursts: {full_name} (last {days} days)")
        table.add_column("Start")
        table.add_column("End")
        table.add_column("Days", justify="right")
        table.add_column("Peak", justify="right")
        table.add_column("Gained", justify="right")
        table.add_column("Severity", justify="right")
        for e in events:
            table.add_row(
                e.start_day.isoformat(),
                e.end_day.isoformat(),
                str(e.duration_days),
                str(e.peak_delta),
                str(e.total_gained),
                f"{e.severity:.1f}x",
            )
        console.print(table)
        if active:
            console.print(
                "[red bold]ACTIVE BURST[/red bold] — the repo is taking off right now."
            )

    _run_async(_impl)


@app.command()
def leaderboard(
    window: int = typer.Option(
        7, "--window", "-w", min=7, max=90, help="Time window in days: 7, 30 or 90."
    ),
    limit: int = typer.Option(
        20, "--limit", "-n", min=1, max=100, help="How many repositories to show."
    ),
) -> None:
    if window not in (7, 30, 90):
        console.print("[red]Error:[/red] --window must be 7, 30 or 90")
        raise typer.Exit(2)

    async def _impl() -> None:
        from analytics import service
        from db.base import SessionFactory

        async with SessionFactory() as session:
            total, scored = await service.leaderboard(
                session, window_days=window, limit=limit, offset=0
            )

        if not scored:
            console.print(
                "[yellow]No tracked repositories with enough snapshot history.[/yellow]"
            )
            return

        table = Table(title=f"Fastest growing ({window}d window)")
        table.add_column("#", justify="right")
        table.add_column("Repository")
        table.add_column("Language")
        table.add_column("Stars", justify="right")
        table.add_column("Per day", justify="right")
        for index, (repo, v, stars) in enumerate(scored, start=1):
            table.add_row(
                str(index),
                repo.full_name,
                repo.language or "—",
                f"{stars:,}",
                f"+{v.stars_per_day:.1f}",
            )
        console.print(table)

    _run_async(_impl)


_ALERT_TYPE_ALIASES = {
    "burst": "burst_started",
    "velocity": "velocity_above",
    "milestone": "stars_reached",
}


@alerts_app.command("add")
def alerts_add(
    full_name: str = typer.Argument(..., metavar="owner/name"),
    alert_type: str = typer.Option(..., "--type", help="burst, velocity or milestone"),
    threshold: float | None = typer.Option(None, "--threshold"),
    window: int | None = typer.Option(None, "--window"),
    disabled: bool = typer.Option(False, "--disabled", help="Create the rule disabled."),
) -> None:
    """Create an alert rule for a tracked repository."""
    kind = _ALERT_TYPE_ALIASES.get(alert_type)
    if kind is None:
        console.print("[red]Error:[/red] --type must be burst, velocity or milestone")
        raise typer.Exit(2)

    async def _impl() -> None:
        from alerts import RuleSpec, validate_rule
        from db.alerts import create_rule
        from db.base import SessionFactory
        from db.repositories import get_repository_by_name

        try:
            spec = validate_rule(
                RuleSpec(kind=kind, threshold=threshold, window_days=window)
            )
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(2) from exc

        async with SessionFactory() as session:
            repo = await get_repository_by_name(session, full_name)
            if repo is None:
                console.print(f"[red]Repository not tracked:[/red] {full_name}")
                raise typer.Exit(1)
            rule = await create_rule(session, repo, spec, enabled=not disabled)
            await session.commit()
        console.print(f"[green]Created alert rule #{rule.id}[/green] for {full_name}.")

    _run_async(_impl)


@alerts_app.command("list")
def alerts_list() -> None:
    """List alert rules."""

    async def _impl() -> None:
        from db.alerts import list_rules
        from db.base import SessionFactory

        async with SessionFactory() as session:
            rules, _total = await list_rules(session)
        if not rules:
            console.print("[yellow]No alert rules configured.[/yellow]")
            return

        table = Table(title="Alert rules")
        table.add_column("ID", justify="right")
        table.add_column("Repository")
        table.add_column("Type")
        table.add_column("Condition")
        table.add_column("Enabled")
        for rule in rules:
            if rule.kind == "velocity_above":
                condition = f">= {rule.threshold:g}/day ({rule.window_days}d)"
            elif rule.kind == "stars_reached":
                condition = f">= {rule.threshold:g} stars"
            else:
                condition = "new burst"
            table.add_row(
                str(rule.id),
                rule.repository.full_name,
                rule.kind,
                condition,
                "yes" if rule.enabled else "no",
            )
        console.print(table)

    _run_async(_impl)


async def _set_alert_rule_enabled(rule_id: int, enabled: bool) -> None:
    from db.alerts import get_rule
    from db.base import SessionFactory

    async with SessionFactory() as session:
        rule = await get_rule(session, rule_id)
        if rule is None:
            console.print(f"[red]Alert rule not found:[/red] {rule_id}")
            raise typer.Exit(1)
        rule.enabled = enabled
        await session.commit()
    state = "enabled" if enabled else "disabled"
    console.print(f"[green]Alert rule #{rule_id} {state}.[/green]")


@alerts_app.command("enable")
def alerts_enable(rule_id: int = typer.Argument(..., min=1)) -> None:
    """Enable an alert rule."""
    _run_async(lambda: _set_alert_rule_enabled(rule_id, True))


@alerts_app.command("disable")
def alerts_disable(rule_id: int = typer.Argument(..., min=1)) -> None:
    """Disable an alert rule."""
    _run_async(lambda: _set_alert_rule_enabled(rule_id, False))


@alerts_app.command("delete")
def alerts_delete(
    rule_id: int = typer.Argument(..., min=1),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete an alert rule while retaining its event history."""
    if not yes and not typer.confirm(f"Delete alert rule #{rule_id}?"):
        raise typer.Abort()

    async def _impl() -> None:
        from db.alerts import delete_rule, get_rule
        from db.base import SessionFactory

        async with SessionFactory() as session:
            rule = await get_rule(session, rule_id)
            if rule is None:
                console.print(f"[red]Alert rule not found:[/red] {rule_id}")
                raise typer.Exit(1)
            await delete_rule(session, rule)
            await session.commit()
        console.print(f"[green]Deleted alert rule #{rule_id}.[/green]")

    _run_async(_impl)
