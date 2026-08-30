from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

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
