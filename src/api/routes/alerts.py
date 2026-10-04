from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from alerts import RuleSpec, validate_rule
from alerts.webhook import deliver_event, deliver_test_endpoint
from api.deps import get_session, require_admin_api_key, require_read_api_key
from api.schemas import (
    AcknowledgeAllOut,
    AlertDeliveryOut,
    AlertEventOut,
    AlertEventUpdate,
    AlertKind,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    AlertSummaryOut,
    DeliveryTestOut,
    NotificationEndpointCreate,
    NotificationEndpointOut,
    NotificationEndpointUpdate,
    Paginated,
)
from config import settings
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
from db.models import AlertDelivery, AlertEvent, AlertRule, NotificationEndpoint
from db.notifications import (
    create_endpoint,
    get_delivery,
    get_endpoint,
    get_endpoint_by_name,
    list_deliveries,
    list_endpoints,
    set_endpoint_enabled,
)
from db.repositories import get_repository_by_name
from security import UnsafeURL, validate_webhook_url

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(require_read_api_key)],
)


def _endpoint_out(endpoint: NotificationEndpoint) -> NotificationEndpointOut:
    return NotificationEndpointOut(
        id=endpoint.id,
        name=endpoint.name,
        provider=endpoint.provider,
        url_configured=bool(endpoint.url),
        enabled=endpoint.enabled,
        failure_count=endpoint.failure_count,
        disabled_at=endpoint.disabled_at,
        last_delivery_at=endpoint.last_delivery_at,
        last_error=endpoint.last_error,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


def _delivery_out(delivery: AlertDelivery) -> AlertDeliveryOut:
    return AlertDeliveryOut(
        id=delivery.id,
        event_id=delivery.event_id,
        endpoint_id=delivery.endpoint_id,
        attempt=delivery.attempt,
        status=delivery.status,
        response_status=delivery.response_status,
        error=delivery.error,
        attempted_at=delivery.attempted_at,
        delivered_at=delivery.delivered_at,
        next_attempt_at=delivery.next_attempt_at,
        created_at=delivery.created_at,
    )


@router.get("/endpoints", response_model=Paginated[NotificationEndpointOut])
async def get_notification_endpoints(
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[NotificationEndpointOut]:
    endpoints, total = await list_endpoints(
        session,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(endpoints) if offset + len(endpoints) < total else None
    return Paginated(
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=[_endpoint_out(endpoint) for endpoint in endpoints],
    )


@router.post(
    "/endpoints",
    response_model=NotificationEndpointOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_api_key)],
)
async def post_notification_endpoint(
    payload: NotificationEndpointCreate,
    session: AsyncSession = Depends(get_session),
) -> NotificationEndpointOut:
    if await get_endpoint_by_name(session, payload.name) is not None:
        raise HTTPException(
            status_code=409, detail="notification endpoint already exists"
        )
    try:
        url = validate_webhook_url(
            payload.url,
            allow_private=settings.webhook_allow_private_addresses,
        )
    except UnsafeURL as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    endpoint = await create_endpoint(
        session,
        name=payload.name,
        provider=payload.provider,
        url=url,
        signing_secret=payload.signing_secret,
    )
    if not payload.enabled:
        await set_endpoint_enabled(session, endpoint, False)
    await session.commit()
    return _endpoint_out(endpoint)


@router.patch(
    "/endpoints/{endpoint_id}",
    response_model=NotificationEndpointOut,
    dependencies=[Depends(require_admin_api_key)],
)
async def patch_notification_endpoint(
    endpoint_id: int,
    payload: NotificationEndpointUpdate,
    session: AsyncSession = Depends(get_session),
) -> NotificationEndpointOut:
    endpoint = await get_endpoint(session, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="notification endpoint not found")
    fields = payload.model_fields_set
    if "url" in fields and payload.url is not None:
        try:
            endpoint.url = validate_webhook_url(
                payload.url,
                allow_private=settings.webhook_allow_private_addresses,
            )
        except UnsafeURL as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "provider" in fields and payload.provider is not None:
        endpoint.provider = payload.provider
    if "signing_secret" in fields:
        endpoint.signing_secret = payload.signing_secret
    if "enabled" in fields and payload.enabled is not None:
        await set_endpoint_enabled(session, endpoint, payload.enabled)
    await session.commit()
    await session.refresh(endpoint)
    return _endpoint_out(endpoint)


@router.delete(
    "/endpoints/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_api_key)],
)
async def delete_notification_endpoint(
    endpoint_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    endpoint = await get_endpoint(session, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="notification endpoint not found")
    await session.delete(endpoint)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/endpoints/{endpoint_id}/test",
    response_model=DeliveryTestOut,
    dependencies=[Depends(require_admin_api_key)],
)
async def test_notification_endpoint(
    endpoint_id: int,
    session: AsyncSession = Depends(get_session),
) -> DeliveryTestOut:
    endpoint = await get_endpoint(session, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="notification endpoint not found")
    sent, error = await deliver_test_endpoint(
        endpoint,
        timeout_seconds=settings.alert_webhook_timeout_seconds,
        max_attempts=settings.webhook_max_attempts,
        backoff_base_seconds=settings.webhook_backoff_base_seconds,
        signing_secret=endpoint.signing_secret or settings.webhook_signing_secret,
    )
    endpoint.last_error = error
    if sent:
        endpoint.failure_count = 0
    await session.commit()
    return DeliveryTestOut(sent=sent, error=error)


@router.get("/deliveries", response_model=Paginated[AlertDeliveryOut])
async def get_notification_deliveries(
    event_id: int | None = Query(default=None, ge=1),
    endpoint_id: int | None = Query(default=None, ge=1),
    delivery_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Paginated[AlertDeliveryOut]:
    deliveries, total = await list_deliveries(
        session,
        event_id=event_id,
        endpoint_id=endpoint_id,
        status=delivery_status,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + len(deliveries) if offset + len(deliveries) < total else None
    return Paginated(
        total=total,
        offset=offset,
        limit=limit,
        next_offset=next_offset,
        items=[_delivery_out(delivery) for delivery in deliveries],
    )


@router.post(
    "/deliveries/{delivery_id}/retry",
    response_model=DeliveryTestOut,
    dependencies=[Depends(require_admin_api_key)],
)
async def retry_notification_delivery(
    delivery_id: int,
    session: AsyncSession = Depends(get_session),
) -> DeliveryTestOut:
    delivery = await get_delivery(session, delivery_id)
    if delivery is None or delivery.endpoint is None:
        raise HTTPException(status_code=404, detail="retryable delivery not found")
    event = delivery.event
    endpoint = delivery.endpoint
    sent = await deliver_event(
        session,
        event,
        webhook_url=endpoint.url,
        timeout_seconds=settings.alert_webhook_timeout_seconds,
        max_attempts=settings.webhook_max_attempts,
        backoff_base_seconds=settings.webhook_backoff_base_seconds,
        signing_secret=endpoint.signing_secret or settings.webhook_signing_secret,
        provider=endpoint.provider,
        endpoint=endpoint,
    )
    return DeliveryTestOut(sent=sent, error=None if sent else event.delivery_error)


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
