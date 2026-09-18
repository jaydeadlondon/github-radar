# Commit 14 — feat: expose alert event inbox API

Reference implementation commit: `4faf2176353176736240182a05af7c78dd566900`
Apply after: `Commit 13`

## Goal

Expose the alert-event inbox, filtering, single/bulk acknowledgement, and summary endpoints.

## Files

### `src/api/routes/alerts.py`

Replace this file with the complete post-commit content below.

````python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from alerts import RuleSpec, validate_rule
from api.deps import get_session
from api.schemas import (
    AcknowledgeAllOut,
    AlertEventOut,
    AlertEventUpdate,
    AlertKind,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    AlertSummaryOut,
    Paginated,
)
from db.alerts import (
    acknowledge_all_events,
    alert_summary,
    create_rule,
    delete_rule,
    get_event,
    get_rule,
    list_events,
    list_rules,
    set_event_acknowledged,
)
from db.models import AlertEvent, AlertRule
from db.repositories import get_repository_by_name

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _validated_spec(spec: RuleSpec) -> RuleSpec:
    try:
        return validate_rule(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _rule_out(rule: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=rule.id,
        repository=rule.repository.full_name,
        kind=rule.kind,
        threshold=rule.threshold,
        window_days=rule.window_days,
        enabled=rule.enabled,
        last_value=rule.last_value,
        last_evaluated_at=rule.last_evaluated_at,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


async def _rule_or_404(session: AsyncSession, rule_id: int) -> AlertRule:
    rule = await get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"alert rule {rule_id} not found")
    return rule


@router.get("/rules", response_model=Paginated[AlertRuleOut])
async def get_rules(
    repository: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[AlertRuleOut]:
    repo_id = None
    if repository:
        repo = await get_repository_by_name(session, repository)
        if repo is None:
            return Paginated(total=0, offset=offset, limit=limit, next_offset=None, items=[])
        repo_id = repo.id
    rules, total = await list_rules(
        session,
        repo_id=repo_id,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(rules) if offset + len(rules) < total else None
    return Paginated(
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=[_rule_out(rule) for rule in rules],
    )


@router.post(
    "/rules",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_rule(
    payload: AlertRuleCreate,
    session: AsyncSession = Depends(get_session),
) -> AlertRuleOut:
    repo = await get_repository_by_name(session, payload.repository)
    if repo is None:
        raise HTTPException(
            status_code=404,
            detail=f"repository {payload.repository} not found",
        )
    spec = _validated_spec(
        RuleSpec(
            kind=payload.kind,
            threshold=payload.threshold,
            window_days=payload.window_days,
        )
    )
    rule = await create_rule(session, repo, spec, enabled=payload.enabled)
    await session.commit()
    return _rule_out(rule)


@router.get("/rules/{rule_id}", response_model=AlertRuleOut)
async def get_rule_by_id(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> AlertRuleOut:
    return _rule_out(await _rule_or_404(session, rule_id))


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
async def patch_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    session: AsyncSession = Depends(get_session),
) -> AlertRuleOut:
    rule = await _rule_or_404(session, rule_id)
    fields = payload.model_fields_set
    spec = _validated_spec(
        RuleSpec(
            kind=payload.kind if "kind" in fields and payload.kind else rule.kind,
            threshold=payload.threshold if "threshold" in fields else rule.threshold,
            window_days=payload.window_days if "window_days" in fields else rule.window_days,
        )
    )
    condition_changed = (
        rule.kind,
        rule.threshold,
        rule.window_days,
    ) != (spec.kind, spec.threshold, spec.window_days)
    rule.kind = spec.kind
    rule.threshold = spec.threshold
    rule.window_days = spec.window_days
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if condition_changed:
        rule.last_value = None
        rule.last_evaluated_at = None
    await session.flush()
    await session.refresh(rule, attribute_names=["updated_at"])
    await session.commit()
    return _rule_out(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    rule = await _rule_or_404(session, rule_id)
    await delete_rule(session, rule)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _event_out(event: AlertEvent) -> AlertEventOut:
    return AlertEventOut(
        id=event.id,
        rule_id=event.rule_id,
        repository=event.repository_full_name,
        kind=event.kind,
        title=event.title,
        message=event.message,
        current_value=event.current_value,
        threshold=event.threshold,
        acknowledged_at=event.acknowledged_at,
        delivery_status=event.delivery_status,
        delivery_error=event.delivery_error,
        created_at=event.created_at,
    )


async def _event_or_404(session: AsyncSession, event_id: int) -> AlertEvent:
    event = await get_event(session, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"alert event {event_id} not found")
    return event


@router.get("/events", response_model=Paginated[AlertEventOut])
async def get_events(
    repository: str | None = Query(default=None),
    kind: AlertKind | None = Query(default=None),
    acknowledged: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[AlertEventOut]:
    events, total = await list_events(
        session,
        repository=repository,
        kind=kind,
        acknowledged=acknowledged,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(events) if offset + len(events) < total else None
    return Paginated(
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=[_event_out(event) for event in events],
    )


@router.post("/events/acknowledge-all", response_model=AcknowledgeAllOut)
async def acknowledge_every_event(
    session: AsyncSession = Depends(get_session),
) -> AcknowledgeAllOut:
    changed = await acknowledge_all_events(session)
    await session.commit()
    return AcknowledgeAllOut(acknowledged=changed)


@router.get("/events/{event_id}", response_model=AlertEventOut)
async def get_event_by_id(
    event_id: int,
    session: AsyncSession = Depends(get_session),
) -> AlertEventOut:
    return _event_out(await _event_or_404(session, event_id))


@router.patch("/events/{event_id}", response_model=AlertEventOut)
async def patch_event(
    event_id: int,
    payload: AlertEventUpdate,
    session: AsyncSession = Depends(get_session),
) -> AlertEventOut:
    event = await _event_or_404(session, event_id)
    await set_event_acknowledged(session, event, payload.acknowledged)
    await session.commit()
    return _event_out(event)


@router.get("/summary", response_model=AlertSummaryOut)
async def get_alert_summary(
    session: AsyncSession = Depends(get_session),
) -> AlertSummaryOut:
    active_rules, unread_events, last_event_at = await alert_summary(session)
    return AlertSummaryOut(
        active_rules=active_rules,
        unread_events=unread_events,
        last_event_at=last_event_at,
    )
````

### `src/api/schemas.py`

Replace this file with the complete post-commit content below.

````python
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    total: int
    offset: int
    limit: int
    next_offset: int | None
    items: list[T]


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stargazers_count: int
    forks_count: int
    open_issues_count: int
    observed_at: datetime


class RepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    stars_per_day: float | None = None


class TrendOut(RepoOut):
    stars_per_day: float


class VelocityOut(BaseModel):
    window_days: int
    stars_per_day: float
    stars_gained: int
    start_day: date
    end_day: date


class RepoDetailOut(BaseModel):
    id: int
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_snapshot: SnapshotOut | None = None
    velocities: list[VelocityOut] = []
    active_burst: bool = False


class ErrorOut(BaseModel):
    detail: str
    code: int


class SlopeOut(BaseModel):
    slope: float
    intercept: float
    r_squared: float
    n_points: int


class RepoBriefOut(BaseModel):
    owner: str
    name: str
    full_name: str
    stars: int


class RepoVelocityOut(BaseModel):
    repo: RepoBriefOut
    velocities: list[VelocityOut]
    trend: SlopeOut | None = None


class SeriesPointOut(BaseModel):
    day: date
    stars: int
    delta: int
    stars_avg: float | None = None
    delta_avg: float | None = None


class RepoSeriesOut(BaseModel):
    repo: RepoBriefOut
    smooth_window: int
    points: list[SeriesPointOut]


class CompareSeriesOut(BaseModel):
    full_name: str
    values: list[float | None]


class CompareOut(BaseModel):
    mode: str
    window_days: int
    days: list[date]
    series: list[CompareSeriesOut]


class BurstOut(BaseModel):
    start_day: date
    end_day: date
    duration_days: int
    peak_day: date
    peak_delta: int
    total_gained: int
    severity: float


class BurstsOut(BaseModel):
    items: list[BurstOut]
    active_burst: bool


class LeaderboardItemOut(BaseModel):
    rank: int
    owner: str
    name: str
    full_name: str
    language: str | None = None
    stars: int
    stars_per_day: float
    stars_gained: int


AlertKind = Literal["burst_started", "velocity_above", "stars_reached"]


class AlertRuleCreate(BaseModel):
    repository: str = Field(min_length=3, max_length=255, pattern=r"^[^/]+/[^/]+$")
    kind: AlertKind
    threshold: float | None = None
    window_days: int | None = None
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    kind: AlertKind | None = None
    threshold: float | None = None
    window_days: int | None = None
    enabled: bool | None = None


class AlertRuleOut(BaseModel):
    id: int
    repository: str
    kind: AlertKind
    threshold: float | None
    window_days: int | None
    enabled: bool
    last_value: float | None
    last_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AlertEventOut(BaseModel):
    id: int
    rule_id: int | None
    repository: str
    kind: AlertKind
    title: str
    message: str
    current_value: float | None
    threshold: float | None
    acknowledged_at: datetime | None
    delivery_status: Literal["inbox_only", "sent", "failed"]
    delivery_error: str | None
    created_at: datetime


class AlertEventUpdate(BaseModel):
    acknowledged: bool


class AlertSummaryOut(BaseModel):
    active_rules: int
    unread_events: int
    last_event_at: datetime | None


class AcknowledgeAllOut(BaseModel):
    acknowledged: int
````

## Verify

```bash
pytest -q tests/test_api_contract.py
ruff check src/api/routes/alerts.py src/api/schemas.py
```

## Commit

```bash
git add -- \
  src/api/routes/alerts.py \
  src/api/schemas.py
git commit -m 'feat: expose alert event inbox API'
```
