from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from alerts import RuleSpec, validate_rule
from api.deps import get_session
from api.schemas import AlertRuleCreate, AlertRuleOut, AlertRuleUpdate, Paginated
from db.alerts import create_rule, delete_rule, get_rule, list_rules
from db.models import AlertRule
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


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    rule = await _rule_or_404(session, rule_id)
    await delete_rule(session, rule)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
