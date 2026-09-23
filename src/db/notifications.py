from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import AlertDelivery, NotificationEndpoint


async def create_endpoint(
    session: AsyncSession,
    *,
    name: str,
    provider: str,
    url: str,
    signing_secret: str | None = None,
) -> NotificationEndpoint:
    endpoint = NotificationEndpoint(
        name=name,
        provider=provider,
        url=url,
        signing_secret=signing_secret,
    )
    session.add(endpoint)
    await session.flush()
    return endpoint


async def get_endpoint(
    session: AsyncSession,
    endpoint_id: int,
) -> NotificationEndpoint | None:
    return await session.get(NotificationEndpoint, endpoint_id)


async def get_endpoint_by_name(
    session: AsyncSession,
    name: str,
) -> NotificationEndpoint | None:
    return await session.scalar(
        select(NotificationEndpoint).where(NotificationEndpoint.name == name)
    )


async def list_endpoints(
    session: AsyncSession,
    *,
    enabled: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[NotificationEndpoint], int]:
    filters = []
    if enabled is not None:
        filters.append(NotificationEndpoint.enabled.is_(enabled))
    total = int(
        await session.scalar(
            select(func.count(NotificationEndpoint.id)).where(*filters)
        )
        or 0
    )
    rows = await session.scalars(
        select(NotificationEndpoint)
        .where(*filters)
        .order_by(
            NotificationEndpoint.created_at.desc(), NotificationEndpoint.id.desc()
        )
        .offset(offset)
        .limit(limit)
    )
    return list(rows), total


async def list_enabled_endpoints(session: AsyncSession) -> list[NotificationEndpoint]:
    rows, _ = await list_endpoints(session, enabled=True, limit=1000)
    return rows


async def get_delivery(
    session: AsyncSession,
    delivery_id: int,
) -> AlertDelivery | None:
    return await session.scalar(
        select(AlertDelivery)
        .options(
            selectinload(AlertDelivery.event),
            selectinload(AlertDelivery.endpoint),
        )
        .where(AlertDelivery.id == delivery_id)
    )


async def list_deliveries(
    session: AsyncSession,
    *,
    event_id: int | None = None,
    endpoint_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AlertDelivery], int]:
    from sqlalchemy import func

    filters = []
    if event_id is not None:
        filters.append(AlertDelivery.event_id == event_id)
    if endpoint_id is not None:
        filters.append(AlertDelivery.endpoint_id == endpoint_id)
    if status is not None:
        filters.append(AlertDelivery.status == status)
    total = int(
        await session.scalar(select(func.count(AlertDelivery.id)).where(*filters)) or 0
    )
    rows = await session.scalars(
        select(AlertDelivery)
        .where(*filters)
        .order_by(AlertDelivery.created_at.desc(), AlertDelivery.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), total


async def set_endpoint_enabled(
    session: AsyncSession,
    endpoint: NotificationEndpoint,
    enabled: bool,
) -> NotificationEndpoint:
    endpoint.enabled = enabled
    endpoint.disabled_at = None if enabled else datetime.now(UTC)
    if enabled:
        endpoint.failure_count = 0
        endpoint.last_error = None
    await session.flush()
    return endpoint
