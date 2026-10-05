#!/usr/bin/env python
"""Offline benchmark for the read paths that scale with history size.

Seeds a throwaway SQLite database (default: 300 repositories x 365 daily
snapshots ~ 110k rows) and times the analytics and dashboard queries that a
production installation runs on every request.  Nothing is downloaded and the
seeded database is deleted afterwards, so the script is safe to run anywhere::

    .venv/bin/python scripts/benchmark.py --repos 300 --days 365
    .venv/bin/python scripts/benchmark.py --plans

``--plans`` additionally prints ``EXPLAIN QUERY PLAN`` output for the seed of
each hot statement, which is how the v1.0 index set was chosen.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _seed(database: Path, repos: int, days: int) -> None:
    from sqlalchemy import create_engine, insert

    from db.models import Base, Repository, RepoSnapshot

    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    today = datetime.now(UTC).date()
    with engine.begin() as connection:
        connection.execute(
            insert(Repository),
            [
                {
                    "id": repo_id,
                    "full_name": f"acme/repo-{repo_id}",
                    "description": "",
                    "html_url": f"https://github.com/acme/repo-{repo_id}",
                    "language": "Python" if repo_id % 2 else "Go",
                    "tracking_enabled": True,
                    "tracking_paused": False,
                }
                for repo_id in range(1, repos + 1)
            ],
        )
        batch: list[dict[str, object]] = []
        for repo_id in range(1, repos + 1):
            for day in range(days):
                batch.append(
                    {
                        "repo_id": repo_id,
                        "stargazers_count": 1000 + repo_id + day * (3 + repo_id % 5),
                        "forks_count": day,
                        "open_issues_count": 0,
                        "observed_at": datetime.combine(
                            today - timedelta(days=days - day),
                            datetime.min.time(),
                            tzinfo=UTC,
                        ),
                        "quality_status": "rejected" if day % 20 == 0 else "accepted",
                    }
                )
                if len(batch) >= 20_000:
                    connection.execute(insert(RepoSnapshot), batch)
                    batch.clear()
        if batch:
            connection.execute(insert(RepoSnapshot), batch)
    engine.dispose()


async def _measure(database: Path, repos: int, plans: bool) -> int:
    os.environ["RADAR_DATABASE_URL"] = f"sqlite+aiosqlite:///{database}"

    from analytics.service import leaderboard, repo_series
    from db.base import SessionFactory
    from db.repositories import top_growth

    async with SessionFactory() as session:
        since = datetime.now(UTC) - timedelta(days=90)
        cases = [
            (
                "leaderboard window=7",
                lambda: leaderboard(session, window_days=7, limit=20, offset=0),
            ),
            (
                "leaderboard window=90",
                lambda: leaderboard(session, window_days=90, limit=20, offset=0),
            ),
            (
                "repo_series history=90d",
                lambda: repo_series(session, 1, history_days=90),
            ),
            ("top_growth window=90d", lambda: top_growth(session, since, limit=10)),
            ("list_repositories page=100", lambda: _list_repositories(session)),
        ]
        if plans:
            await _print_plans(session)
        failures = 0
        print(f"{'case':<28} {'rows':>6}  {'time':>10}")
        for name, factory in cases:
            started = time.perf_counter()
            result = await factory()
            elapsed = time.perf_counter() - started
            if isinstance(result, tuple):
                size = len(result[0]) if isinstance(result[0], list) else result[0]
            else:
                size = len(result)
            print(f"{name:<28} {size:>6}  {elapsed * 1000:>7.1f} ms")
            if elapsed > 5.0:
                failures += 1
    return failures


async def _list_repositories(session) -> tuple[list, int]:
    from db.repositories import list_repositories

    return await list_repositories(session, sort="stars", limit=100, offset=0)


async def _print_plans(session) -> None:
    from sqlalchemy import select, text

    from db.models import RepoSnapshot

    statements = {
        "latest snapshot per repo": (
            select(RepoSnapshot.repo_id, text("max(observed_at)"))
            .where(RepoSnapshot.quality_status.in_(("accepted", "anomalous")))
            .group_by(RepoSnapshot.repo_id)
        ),
        "history window": (
            select(RepoSnapshot.id)
            .where(
                RepoSnapshot.repo_id == 1,
                RepoSnapshot.quality_status.in_(("accepted", "anomalous")),
                RepoSnapshot.observed_at >= datetime(2000, 1, 1, tzinfo=UTC),
            )
            .order_by(RepoSnapshot.observed_at, RepoSnapshot.id)
        ),
    }
    print("query plans:")
    for name, statement in statements.items():
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        plan = (await session.execute(text(f"EXPLAIN QUERY PLAN {sql}"))).fetchall()
        print(f"  {name}:")
        for row in plan:
            print(f"    {row[-1]}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos", type=int, default=300)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--plans", action="store_true")
    parser.add_argument("--keep", action="store_true", help="keep the seeded database")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="radar-bench-") as tmp:
        database = Path(tmp) / "bench.db"
        print(f"seeding {args.repos} repos x {args.days} days into {database}")
        started = time.perf_counter()
        _seed(database, args.repos, args.days)
        print(f"seeded in {time.perf_counter() - started:.1f}s\n")
        failures = asyncio.run(_measure(database, args.repos, args.plans))
        size = database.stat().st_size / (1024 * 1024)
        print(f"\ndatabase size: {size:.1f} MB")
        if args.keep:
            target = ROOT / "bench.db"
            target.write_bytes(database.read_bytes())
            print(f"kept a copy at {target}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
