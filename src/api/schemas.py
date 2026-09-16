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
