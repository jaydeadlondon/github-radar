from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_session

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthOut, summary="Service health check")
async def health(session: AsyncSession = Depends(get_session)) -> HealthOut:
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        database=database,
    )
