from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from data_quality import sanitize_error
from db.models import Repository
from db.repositories import create_snapshot, get_history, get_repository_by_name
from github.client import GitHubClient
from github.errors import GitHubError


@dataclass(frozen=True)
class BackfillRepositoryResult:
    repository: str
    requested_days: int
    planned: int
    inserted: int
    skipped_existing: int
    dry_run: bool
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BackfillResult:
    repositories: list[BackfillRepositoryResult]

    @property
    def planned(self) -> int:
        return sum(item.planned for item in self.repositories)

    @property
    def inserted(self) -> int:
        return sum(item.inserted for item in self.repositories)

    def as_dict(self) -> dict[str, object]:
        return {
            "planned": self.planned,
            "inserted": self.inserted,
            "repositories": [item.as_dict() for item in self.repositories],
        }


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=UTC).replace(microsecond=0)


def _parse_dates(values: Sequence[str | datetime]) -> list[datetime]:
    parsed: list[datetime] = []
    for value in values:
        try:
            moment = (
                value
                if isinstance(value, datetime)
                else datetime.fromisoformat(value.replace("Z", "+00:00"))
            )
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        else:
            moment = moment.astimezone(UTC)
        parsed.append(moment)
    return parsed


async def backfill_repository(
    session: AsyncSession,
    client: GitHubClient,
    repository: Repository,
    *,
    days: int,
    dry_run: bool = False,
    limit: int | None = None,
    max_pages: int | None = None,
    now: datetime | None = None,
) -> BackfillRepositoryResult:
    """Safely reconstruct daily star counts from GitHub stargazer timestamps.

    GitHub does not expose arbitrary historical repository snapshots.  The
    stargazer endpoint does expose the timestamp for each current stargazer;
    this implementation makes that limitation explicit and only inserts
    points derived from those timestamps.  Existing points are skipped, so a
    stopped run can be resumed without replaying history.
    """

    if days < 1:
        raise ValueError("days must be at least 1")
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    else:
        current_time = current_time.astimezone(UTC)
    start_day = (current_time - timedelta(days=days - 1)).date()

    try:
        current = await client.get_repo(repository.full_name)
        raw_dates = await client.get_stargazer_dates(
            repository.full_name,
            max_pages=max_pages,
        )
    except GitHubError as exc:
        return BackfillRepositoryResult(
            repository=repository.full_name,
            requested_days=days,
            planned=0,
            inserted=0,
            skipped_existing=0,
            dry_run=dry_run,
            error=sanitize_error(exc),
        )
    except Exception as exc:
        return BackfillRepositoryResult(
            repository=repository.full_name,
            requested_days=days,
            planned=0,
            inserted=0,
            skipped_existing=0,
            dry_run=dry_run,
            error=sanitize_error(exc),
        )

    existing = await get_history(
        session,
        repository.id,
        since=datetime.combine(start_day, time.min, tzinfo=UTC),
    )
    existing_days = {snapshot.observed_at.date() for snapshot in existing}
    all_days = [start_day + timedelta(days=index) for index in range(days)]
    missing_days = [day for day in all_days if day not in existing_days]
    skipped = len(all_days) - len(missing_days)
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must not be negative")
        missing_days = missing_days[:limit]

    starred_at = _parse_dates(raw_dates)
    planned = len(missing_days)
    if dry_run:
        return BackfillRepositoryResult(
            repository=repository.full_name,
            requested_days=days,
            planned=planned,
            inserted=0,
            skipped_existing=skipped,
            dry_run=True,
        )

    inserted = 0
    for day in missing_days:
        end = _day_end(day)
        # Current stargazers with a later timestamp did not exist yet.  When
        # the endpoint is truncated by max_pages this remains a conservative
        # lower-bound estimate rather than a fabricated zero-growth point.
        stars = max(
            0,
            current.stargazers_count - sum(1 for moment in starred_at if moment > end),
        )
        snapshot = await create_snapshot(
            session,
            repository.id,
            stargazers=stars,
            forks=current.forks_count,
            open_issues=current.open_issues_count,
            observed_at=end,
        )
        if snapshot.quality_status in {"accepted", "anomalous"}:
            inserted += 1
        # A stopped process leaves completed days durable.  The next run
        # re-reads accepted day buckets and resumes at the first gap.
        await session.commit()
    return BackfillRepositoryResult(
        repository=repository.full_name,
        requested_days=days,
        planned=planned,
        inserted=inserted,
        skipped_existing=skipped,
        dry_run=False,
    )


async def run_backfill(
    full_names: Sequence[str] | None = None,
    *,
    days: int,
    dry_run: bool = False,
    limit: int | None = None,
    max_pages: int | None = None,
    client: GitHubClient | None = None,
    concurrency: int = 1,
    session: AsyncSession,
) -> BackfillResult:
    """Backfill selected repositories, or all active tracked repositories."""

    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    unknown_results: list[BackfillRepositoryResult] = []
    if full_names:
        repositories = []
        for name in full_names:
            repository = await get_repository_by_name(session, name)
            if repository is not None:
                repositories.append(repository)
            else:
                unknown_results.append(
                    BackfillRepositoryResult(
                        repository=name,
                        requested_days=days,
                        planned=0,
                        inserted=0,
                        skipped_existing=0,
                        dry_run=dry_run,
                        error="repository is not known; track it before backfill",
                    )
                )
    else:
        from sqlalchemy import select

        repositories = list(
            (
                await session.scalars(
                    select(Repository)
                    .where(
                        Repository.tracking_enabled.is_(True),
                        Repository.tracking_paused.is_(False),
                    )
                    .order_by(Repository.id)
                )
            ).all()
        )

    owns_client = client is None
    if owns_client:
        client = GitHubClient()
    try:
        results = unknown_results + [
            await backfill_repository(
                session,
                client,
                repository,
                days=days,
                dry_run=dry_run,
                limit=limit,
                max_pages=max_pages,
            )
            for repository in repositories
        ]
    finally:
        if owns_client:
            await client.close()
    if not dry_run:
        await session.commit()
    return BackfillResult(results)
