from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from alerts.service import (
    evaluate_burst_rule,
    evaluate_milestone_rule,
    evaluate_velocity_rule,
)
from alerts.types import BURST_STARTED, STARS_REACHED, VELOCITY_ABOVE
from alerts.webhook import deliver_event
from analytics import service as analytics_service
from analytics.bursts import detect_bursts
from analytics.velocity import window_velocity
from config import settings
from db.alerts import list_enabled_rules
from db.base import SessionFactory
from db.models import AlertEvent, AlertRule
from db.notifications import list_enabled_endpoints
from db.repositories import get_latest_snapshot
from observability import metrics


async def evaluate_rules(
    session: AsyncSession,
    repo_ids: Sequence[int],
    *,
    evaluated_at: datetime | None = None,
    webhook_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[AlertEvent]:
    """Evaluate enabled rules for freshly updated repositories."""
    rules = await list_enabled_rules(session, repo_ids)
    if not rules:
        return []

    now = evaluated_at or datetime.now(UTC)
    by_repo: dict[int, list[AlertRule]] = {}
    for rule in rules:
        by_repo.setdefault(rule.repo_id, []).append(rule)

    inserted: list[AlertEvent] = []
    for repo_id, repo_rules in by_repo.items():
        latest = await get_latest_snapshot(session, repo_id)
        if latest is None:
            continue

        series = None
        bursts = None
        for rule in repo_rules:
            if rule.kind == STARS_REACHED:
                event = await evaluate_milestone_rule(
                    session,
                    rule,
                    latest.stargazers_count,
                    evaluated_at=now,
                )
                if event is not None:
                    inserted.append(event)
                continue

            if series is None:
                series = await analytics_service.repo_series(
                    session,
                    repo_id,
                    history_days=settings.analytics_history_days,
                )

            if rule.kind == VELOCITY_ABOVE:
                if rule.window_days is None:
                    continue
                velocity = window_velocity(series, rule.window_days)
                if velocity is None:
                    rule.last_evaluated_at = now
                    continue
                event = await evaluate_velocity_rule(
                    session,
                    rule,
                    velocity.stars_per_day,
                    evaluated_at=now,
                )
                if event is not None:
                    inserted.append(event)
                continue

            if rule.kind == BURST_STARTED:
                if bursts is None:
                    bursts = detect_bursts(
                        series,
                        rolling_window=settings.analytics_rolling_window,
                        z_threshold=settings.analytics_burst_z,
                        min_delta=settings.analytics_burst_min_delta,
                        min_duration=settings.analytics_burst_min_days,
                    )
                inserted.extend(
                    await evaluate_burst_rule(
                        session,
                        rule,
                        bursts,
                        evaluated_at=now,
                    )
                )

    for event in inserted:
        metrics.increment("alert_events", labels={"kind": event.kind})

    if webhook_url is None:
        endpoints = await list_enabled_endpoints(session)
    else:
        endpoints = []
    destination = settings.alert_webhook_url if webhook_url is None else webhook_url
    delivery_attempts = settings.webhook_max_attempts if webhook_url is None else 1
    for event in inserted:
        if endpoints:
            for endpoint in endpoints:
                await deliver_event(
                    session,
                    event,
                    webhook_url=endpoint.url,
                    timeout_seconds=settings.alert_webhook_timeout_seconds,
                    transport=transport,
                    max_attempts=delivery_attempts,
                    backoff_base_seconds=settings.webhook_backoff_base_seconds,
                    signing_secret=endpoint.signing_secret or settings.webhook_signing_secret,
                    provider=endpoint.provider,
                    endpoint=endpoint,
                )
        else:
            await deliver_event(
                session,
                event,
                webhook_url=destination,
                timeout_seconds=settings.alert_webhook_timeout_seconds,
                transport=transport,
                max_attempts=delivery_attempts,
                backoff_base_seconds=settings.webhook_backoff_base_seconds,
                signing_secret=settings.webhook_signing_secret,
                provider=settings.webhook_provider,
            )
    return inserted


async def run_alert_evaluation(repo_ids: Sequence[int]) -> int:
    if not settings.alerts_enabled or not repo_ids:
        return 0
    async with SessionFactory() as session:
        events = await evaluate_rules(session, repo_ids)
        await session.commit()
        return len(events)
