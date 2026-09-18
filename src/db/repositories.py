from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from data_quality import SnapshotQuality, inspect_snapshot, normalize_utc
from db.models import Repository, RepoSnapshot
from github.models import RepoSummary

ACCEPTED_QUALITY_STATUSES: Final[tuple[str, ...]] = (
    SnapshotQuality.ACCEPTED.value,
    SnapshotQuality.ANOMALOUS.value,
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def update_repository_metadata(
    session: AsyncSession,
    repository: Repository,
    repo: RepoSummary,
) -> Repository:
    """Update GitHub-owned metadata without changing tracking controls."""

    repository.description = repo.description
    repository.html_url = repo.html_url
    repository.language = repo.language
    repository.github_created_at = _parse_dt(repo.created_at)
    repository.github_pushed_at = _parse_dt(repo.pushed_at)
    repository.default_branch = getattr(repo, "default_branch", None)
    if getattr(repo, "archived", False):
        repository.archived_at = repository.archived_at or datetime.now(UTC)
    else:
        repository.archived_at = None
    await session.flush()
    return repository


async def upsert_repository(
    session: AsyncSession,
    repo: RepoSummary,
    *,
    track: bool | None = True,
    tracking_label: str | None = None,
) -> Repository:
    """Create or update a known repository.

    ``track=None`` is used by the snapshot pipeline so refreshing metadata does
    not accidentally re-enable a repository the user paused or removed.
    Search/top ``--save`` retains the v0.7 behaviour by using the default and
    explicitly making the repository active.
    """

    existing = await session.scalar(
        select(Repository).where(Repository.full_name == repo.full_name)
    )
    if existing is None:
        existing = Repository(
            full_name=repo.full_name,
            description=repo.description,
            html_url=repo.html_url,
            language=repo.language,
            github_created_at=_parse_dt(repo.created_at),
            github_pushed_at=_parse_dt(repo.pushed_at),
            default_branch=getattr(repo, "default_branch", None),
            archived_at=(
                datetime.now(UTC) if getattr(repo, "archived", False) else None
            ),
            tracking_enabled=True if track is None else track,
            tracking_paused=False,
            tracking_label=tracking_label,
        )
        session.add(existing)
    else:
        await update_repository_metadata(session, existing, repo)
        if track is not None:
            existing.tracking_enabled = track
            if track:
                existing.tracking_paused = False
        if tracking_label is not None:
            existing.tracking_label = tracking_label
    await session.flush()
    return existing


async def get_latest_accepted_snapshot(
    session: AsyncSession,
    repo_id: int,
    *,
    before: datetime | None = None,
) -> RepoSnapshot | None:
    stmt = (
        select(RepoSnapshot)
        .where(
            RepoSnapshot.repo_id == repo_id,
            RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES),
        )
        .order_by(RepoSnapshot.observed_at.desc(), RepoSnapshot.id.desc())
        .limit(1)
    )
    if before is not None:
        stmt = stmt.where(RepoSnapshot.observed_at < normalize_utc(before))
    return await session.scalar(stmt)


async def create_snapshot(
    session: AsyncSession,
    repo_id: int,
    *,
    stargazers: int,
    forks: int,
    open_issues: int = 0,
    observed_at: datetime | None = None,
    allow_decrease: bool = False,
) -> RepoSnapshot:
    """Persist one quality-checked observation.

    Observations with the same repository and UTC timestamp are idempotent and
    return the original row.  A rejected observation is retained for audit but
    excluded from analytics and latest-value queries.  This prevents API
    failures or malformed payloads from becoming a misleading zero delta.
    """

    normalized_at = normalize_utc(observed_at)
    duplicate = await session.scalar(
        select(RepoSnapshot)
        .where(
            RepoSnapshot.repo_id == repo_id,
            RepoSnapshot.observed_at == normalized_at,
        )
        .order_by(RepoSnapshot.id)
        .limit(1)
    )
    if duplicate is not None:
        return duplicate

    previous = await get_latest_accepted_snapshot(
        session,
        repo_id,
        before=normalized_at,
    )
    check = inspect_snapshot(
        stargazers=stargazers,
        forks=forks,
        open_issues=open_issues,
        previous_stars=previous.stargazers_count if previous else None,
        allow_decrease=allow_decrease,
    )
    snapshot = RepoSnapshot(
        repo_id=repo_id,
        stargazers_count=stargazers,
        forks_count=forks,
        open_issues_count=open_issues,
        observed_at=normalized_at,
        quality_status=check.status.value,
        quality_reason=check.reason,
    )
    session.add(snapshot)
    await session.flush()

    repository = await session.get(Repository, repo_id)
    if repository is not None:
        attempt = repository.last_snapshot_attempt_at
        if check.accepted:
            if (
                repository.last_successful_snapshot_at is None
                or normalize_utc(repository.last_successful_snapshot_at) <= normalized_at
            ):
                repository.last_successful_snapshot_at = normalized_at
                repository.last_snapshot_error = None
            if attempt is None or normalize_utc(attempt) <= normalized_at:
                repository.last_snapshot_attempt_at = normalized_at
        else:
            if attempt is None or normalize_utc(attempt) <= normalized_at:
                repository.last_snapshot_attempt_at = normalized_at
            repository.last_snapshot_error = (
                f"snapshot rejected: {check.reason or 'quality check failed'}"
            )
        await session.flush()
    return snapshot


async def get_latest_snapshot(
    session: AsyncSession,
    repo_id: int,
    *,
    include_rejected: bool = False,
) -> RepoSnapshot | None:
    stmt = (
        select(RepoSnapshot)
        .where(RepoSnapshot.repo_id == repo_id)
        .order_by(RepoSnapshot.observed_at.desc(), RepoSnapshot.id.desc())
        .limit(1)
    )
    if not include_rejected:
        stmt = stmt.where(RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES))
    return await session.scalar(stmt)


async def get_history(
    session: AsyncSession,
    repo_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
    *,
    include_rejected: bool = False,
) -> list[RepoSnapshot]:
    stmt = (
        select(RepoSnapshot)
        .where(RepoSnapshot.repo_id == repo_id)
        .order_by(RepoSnapshot.observed_at, RepoSnapshot.id)
    )
    if not include_rejected:
        stmt = stmt.where(RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES))
    if since is not None:
        stmt = stmt.where(RepoSnapshot.observed_at >= normalize_utc(since))
    if until is not None:
        stmt = stmt.where(RepoSnapshot.observed_at <= normalize_utc(until))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(await session.scalars(stmt))


async def top_growth(
    session: AsyncSession,
    since: datetime,
    *,
    limit: int = 10,
) -> list[tuple[Repository, int]]:
    rows = await session.execute(
        select(Repository, RepoSnapshot)
        .join(
            RepoSnapshot,
            and_(
                RepoSnapshot.repo_id == Repository.id,
                RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES),
            ),
        )
        .where(
            Repository.tracking_enabled.is_(True),
            RepoSnapshot.observed_at >= normalize_utc(since),
        )
        .order_by(Repository.id, RepoSnapshot.observed_at, RepoSnapshot.id)
    )
    deltas: dict[int, tuple[Repository, int, int, int, int]] = {}
    for repo, snapshot in rows:
        if repo.id not in deltas:
            deltas[repo.id] = (
                repo,
                snapshot.stargazers_count,
                snapshot.stargazers_count,
                snapshot.stargazers_count,
                snapshot.forks_count,
            )
        else:
            stored, first_stars, _, _, _ = deltas[repo.id]
            deltas[repo.id] = (
                stored,
                first_stars,
                snapshot.stargazers_count,
                snapshot.stargazers_count,
                snapshot.forks_count,
            )
    for repo, _first, _last, latest_stars, latest_forks in deltas.values():
        repo.latest_stargazers = latest_stars
        repo.latest_forks = latest_forks
    ranked = sorted(
        ((repo, last - first) for repo, first, last, _ls, _lf in deltas.values()),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[:limit]


async def fetch_histories(
    session: AsyncSession,
    repo_ids: Sequence[int],
    *,
    since: datetime,
    include_rejected: bool = False,
) -> dict[int, list[RepoSnapshot]]:
    ids = list(repo_ids)
    if not ids:
        return {}
    stmt = (
        select(RepoSnapshot)
        .where(
            RepoSnapshot.repo_id.in_(ids),
            RepoSnapshot.observed_at >= normalize_utc(since),
        )
        .order_by(RepoSnapshot.repo_id, RepoSnapshot.observed_at, RepoSnapshot.id)
    )
    if not include_rejected:
        stmt = stmt.where(RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES))
    result = await session.execute(stmt)
    grouped: dict[int, list[RepoSnapshot]] = {}
    for snapshot in result.scalars():
        grouped.setdefault(snapshot.repo_id, []).append(snapshot)
    return grouped


async def snapshot_stats(
    session: AsyncSession,
    repo_id: int,
) -> tuple[int, datetime | None]:
    """Return accepted snapshot count and the first accepted observation."""

    count, first = (
        await session.execute(
            select(func.count(RepoSnapshot.id), func.min(RepoSnapshot.observed_at)).where(
                RepoSnapshot.repo_id == repo_id,
                RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES),
            )
        )
    ).one()
    return int(count or 0), first


async def get_repository_by_name(
    session: AsyncSession,
    full_name: str,
) -> Repository | None:
    repository = await session.scalar(
        select(Repository).where(Repository.full_name == full_name)
    )
    if repository is not None:
        return repository
    # GitHub repository names are case-insensitive; accepting a differently
    # cased path avoids creating a second tracking row for the same project.
    return await session.scalar(
        select(Repository).where(func.lower(Repository.full_name) == full_name.lower())
    )


async def list_repositories(
    session: AsyncSession,
    *,
    language: str | None = None,
    sort: str = "stars",
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
    tracking: str | None = "tracked",
    label: str | None = None,
) -> tuple[list[Repository], int]:
    latest = (
        select(
            RepoSnapshot.repo_id,
            func.max(RepoSnapshot.observed_at).label("latest_at"),
        )
        .where(RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES))
        .group_by(RepoSnapshot.repo_id)
        .subquery()
    )
    rows = (
        select(Repository, RepoSnapshot.stargazers_count, RepoSnapshot.forks_count)
        .join(latest, latest.c.repo_id == Repository.id, isouter=True)
        .join(
            RepoSnapshot,
            and_(
                RepoSnapshot.repo_id == latest.c.repo_id,
                RepoSnapshot.observed_at == latest.c.latest_at,
                RepoSnapshot.quality_status.in_(ACCEPTED_QUALITY_STATUSES),
            ),
            isouter=True,
        )
    )
    filters = []
    if language:
        filters.append(Repository.language == language)
    if search:
        filters.append(Repository.full_name.ilike(f"%{search}%"))
    if label:
        filters.append(Repository.tracking_label == label)
    if tracking in {"tracked", "active"}:
        filters.append(Repository.tracking_enabled.is_(True))
        if tracking == "active":
            filters.append(Repository.tracking_paused.is_(False))
    elif tracking == "paused":
        filters.extend(
            [Repository.tracking_enabled.is_(True), Repository.tracking_paused.is_(True)]
        )
    elif tracking == "untracked":
        filters.append(Repository.tracking_enabled.is_(False))
    elif tracking not in {None, "all"}:
        raise ValueError("tracking must be tracked, active, paused, untracked or all")
    if filters:
        rows = rows.where(*filters)

    total = int(
        (
            await session.execute(
                select(func.count(Repository.id)).where(*filters)
            )
        ).scalar_one()
    )

    if sort == "name":
        rows = rows.order_by(Repository.full_name)
    elif sort == "updated":
        rows = rows.order_by(Repository.updated_at.desc(), Repository.id.desc())
    else:
        rows = rows.order_by(RepoSnapshot.stargazers_count.desc().nulls_last(), Repository.id)

    rows = rows.offset(offset).limit(limit)

    result = []
    for repo, stars, forks in await session.execute(rows):
        repo.latest_stargazers = stars if stars is not None else 0
        repo.latest_forks = forks if forks is not None else 0
        result.append(repo)
    return result, total
