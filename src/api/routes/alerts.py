from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from alerts import RuleSpec, validate_rule
from api.deps import get_session, require_admin_api_key
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
            return Paginated(
                total=0, offset=offset, limit=limit, next_offset=None, items=[]
            )
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
    dependencies=[Depends(require_admin_api_key)],
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


@router.patch(
    "/rules/{rule_id}",
    response_model=AlertRuleOut,
    dependencies=[Depends(require_admin_api_key)],
)
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
            window_days=(
                payload.window_days if "window_days" in fields else rule.window_days
            ),
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


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_api_key)],
)
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


@router.post(
    "/events/acknowledge-all",
    response_model=AcknowledgeAllOut,
    dependencies=[Depends(require_admin_api_key)],
)
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


@router.patch(
    "/events/{event_id}",
    response_model=AlertEventOut,
    dependencies=[Depends(require_admin_api_key)],
)
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
