from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.alerts import set_delivery_result
from db.models import AlertDelivery, AlertEvent, NotificationEndpoint
from observability import metrics
from security import UnsafeURL, validate_outbound_url

logger = logging.getLogger(__name__)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def build_webhook_payload(event: AlertEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "kind": event.kind,
        "repository": event.repository_full_name,
        "title": event.title,
        "message": event.message,
        "current_value": event.current_value,
        "threshold": event.threshold,
        "created_at": _utc_iso(event.created_at),
        "repository_url": f"https://github.com/{event.repository_full_name}",
    }


def build_provider_payload(event: AlertEvent, provider: str) -> dict[str, Any]:
    payload = build_webhook_payload(event)
    if provider == "slack":
        return {"text": f"{event.title}: {event.message}"}
    if provider == "discord":
        return {"content": f"**{event.title}** — {event.message}"}
    return payload


def _delivery_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: webhook request failed"


def _retryable(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return True


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _create_delivery(
    session: AsyncSession,
    event: AlertEvent,
    *,
    endpoint_id: int | None,
    attempt: int,
    now: datetime,
) -> AlertDelivery:
    delivery = AlertDelivery(
        event_id=event.id,
        endpoint_id=endpoint_id,
        attempt=attempt,
        status="pending",
        attempted_at=now,
    )
    session.add(delivery)
    await session.flush()
    await session.commit()
    return delivery


async def deliver_test_endpoint(
    endpoint: NotificationEndpoint,
    *,
    timeout_seconds: float = 10.0,
    max_attempts: int = 1,
    backoff_base_seconds: float = 1.0,
    signing_secret: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[bool, str | None]:
    payload = {
        "event": "test",
        "provider": endpoint.provider,
        "endpoint": endpoint.name,
        "message": "GitHub Radar webhook test",
        "created_at": _utc_iso(datetime.now(UTC)),
    }
    if endpoint.provider == "slack":
        payload = {"text": "GitHub Radar webhook test"}
    elif endpoint.provider == "discord":
        payload = {"content": "GitHub Radar webhook test"}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    try:
        validate_outbound_url(endpoint.url)
    except UnsafeURL as exc:
        return False, f"blocked target: {exc}"

    attempts = max(max_attempts, 1)
    for attempt in range(1, attempts + 1):
        headers = {"Content-Type": "application/json"}
        if signing_secret:
            headers["X-GitHub-Radar-Signature-256"] = _signature(body, signing_secret)
        try:
            async with httpx.AsyncClient(
                timeout=max(timeout_seconds, 0.1),
                transport=transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    endpoint.url, content=body, headers=headers
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            error = _delivery_error(exc)[:200]
            if attempt < attempts and _retryable(exc):
                await asyncio.sleep(max(backoff_base_seconds, 0) * (2 ** (attempt - 1)))
                continue
            return False, error
        return True, None
    return False, "webhook test failed"


async def deliver_event(
    session: AsyncSession,
    event: AlertEvent,
    *,
    webhook_url: str,
    timeout_seconds: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
    max_attempts: int = 1,
    backoff_base_seconds: float = 1.0,
    signing_secret: str | None = None,
    provider: str = "generic",
    endpoint: NotificationEndpoint | None = None,
) -> bool:
    if not webhook_url.strip():
        await set_delivery_result(session, event, status="inbox_only")
        return True

    try:
        validate_outbound_url(webhook_url)
    except UnsafeURL:
        await set_delivery_result(
            session,
            event,
            status="failed",
            error="webhook target address is not allowed",
        )
        metrics.increment("webhook_deliveries", labels={"result": "blocked"})
        logger.warning(
            "webhook delivery blocked",
            extra={
                "event_id": event.id,
                "endpoint_id": endpoint.id if endpoint else None,
                "operation": "webhook_delivery",
                "result": "blocked",
                "error_category": "unsafe_target",
                "repository": event.repository_full_name,
            },
        )
        return False

    attempts = max(max_attempts, 1)
    for attempt in range(1, attempts + 1):
        now = datetime.now(UTC)
        delivery = await _create_delivery(
            session,
            event,
            endpoint_id=endpoint.id if endpoint else None,
            attempt=attempt,
            now=now,
        )
        body = json.dumps(
            build_provider_payload(event, provider),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if signing_secret:
            headers["X-GitHub-Radar-Signature-256"] = _signature(body, signing_secret)

        try:
            async with httpx.AsyncClient(
                timeout=max(timeout_seconds, 0.1),
                transport=transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    webhook_url,
                    content=body,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            error = _delivery_error(exc)[:200]
            retry = attempt < attempts and _retryable(exc)
            delay = max(backoff_base_seconds, 0) * (2 ** (attempt - 1))
            delivery.status = "failed"
            delivery.response_status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            delivery.error = error
            delivery.next_attempt_at = now + timedelta(seconds=delay) if retry else None
            event.delivery_status = "failed"
            event.delivery_error = error
            metrics.increment("webhook_deliveries", labels={"result": "failed"})
            logger.warning(
                "webhook delivery failed",
                extra={
                    "event_id": event.id,
                    "delivery_id": delivery.id,
                    "endpoint_id": endpoint.id if endpoint else None,
                    "operation": "webhook_delivery",
                    "result": "retry" if retry else "failed",
                    "error_category": type(exc).__name__,
                    "repository": event.repository_full_name,
                },
            )
            if endpoint is not None:
                endpoint.failure_count += 1
                endpoint.last_error = error
                if endpoint.failure_count >= settings.webhook_disable_after_failures:
                    endpoint.enabled = False
                    endpoint.disabled_at = now
            await session.commit()
            if retry:
                await asyncio.sleep(delay)
                continue
            return False

        delivery.status = "sent"
        delivery.response_status = response.status_code
        delivery.delivered_at = datetime.now(UTC)
        delivery.error = None
        event.delivery_status = "sent"
        event.delivery_error = None
        metrics.increment("webhook_deliveries", labels={"result": "sent"})
        logger.info(
            "webhook delivery sent",
            extra={
                "event_id": event.id,
                "delivery_id": delivery.id,
                "endpoint_id": endpoint.id if endpoint else None,
                "operation": "webhook_delivery",
                "result": "sent",
                "repository": event.repository_full_name,
            },
        )
        if endpoint is not None:
            endpoint.failure_count = 0
            endpoint.last_delivery_at = delivery.delivered_at
            endpoint.last_error = None
        await session.commit()
        return True

    return False
