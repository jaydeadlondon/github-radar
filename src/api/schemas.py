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


class SnapshotQualityOut(SnapshotOut):
    quality_status: Literal["accepted", "anomalous", "rejected"]
    quality_reason: str | None = None


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
    tracking_enabled: bool = True
    tracking_paused: bool = False
    tracking_label: str | None = None
    tracking_status: str = "healthy"
    last_successful_snapshot_at: datetime | None = None
    last_snapshot_attempt_at: datetime | None = None
    last_snapshot_error: str | None = None
    snapshot_count: int = 0
    history_start_at: datetime | None = None
    next_snapshot_at: datetime | None = None


class TrendOut(RepoOut):
    stars_per_day: float


class VelocityOut(BaseModel):
    window_days: int
    stars_per_day: float
    stars_gained: int
    start_day: date
    end_day: date


TrackingStatusValue = Literal["healthy", "stale", "failed", "paused", "untracked"]


class TrackingStatusOut(BaseModel):
    id: int
    repository: str
    tracking_enabled: bool
    tracking_paused: bool
    label: str | None = None
    tracking_label: str | None = None
    status: TrackingStatusValue
    tracking_status: TrackingStatusValue | None = None
    last_successful_snapshot_at: datetime | None = None
    last_snapshot_attempt_at: datetime | None = None
    last_snapshot_error: str | None = None
    snapshot_count: int
    history_start_at: datetime | None = None
    next_snapshot_at: datetime | None = None
    archived_at: datetime | None = None
    default_branch: str | None = None


class TrackingUpdate(BaseModel):
    enabled: bool | None = None
    paused: bool | None = None
    label: str | None = Field(default=None, max_length=100)
    tracking_enabled: bool | None = None
    tracking_paused: bool | None = None
    tracking_label: str | None = Field(default=None, max_length=100)


class TrackingTrackIn(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    tracking_label: str | None = Field(default=None, max_length=100)


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
    tracking: TrackingStatusOut | None = None
    tracking_enabled: bool = True
    tracking_paused: bool = False
    tracking_label: str | None = None
    tracking_status: TrackingStatusValue = "healthy"


class ErrorOut(BaseModel):
    detail: str
    code: int
    type: str = "error"
    request_id: str | None = None


class RateLimitOut(BaseModel):
    resource: str
    limit: int
    remaining: int
    used: int
    reset_at: datetime | None = None
    warning: str | None = None


class ReadyOut(BaseModel):
    status: Literal["ready", "not_ready"]
    database: str
    migrations: str
    detail: str | None = None


class ConfigDiagnosticsOut(BaseModel):
    environment: str
    api_auth_enabled: bool
    admin_key_configured: bool
    read_key_configured: bool
    database_backend: str
    scheduler_enabled: bool
    webhook_provider: str
    insecure_warnings: list[str]


JobStatusValue = Literal["running", "succeeded", "failed", "skipped"]


class SnapshotJobOut(BaseModel):
    id: str
    job_type: str
    status: JobStatusValue
    started_at: datetime
    finished_at: datetime | None
    total_repositories: int
    succeeded_repositories: int
    failed_repositories: int
    error: str | None
    created_at: datetime
    updated_at: datetime


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


NotificationProvider = Literal["generic", "slack", "discord"]


class NotificationEndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    provider: NotificationProvider = "generic"
    url: str = Field(min_length=8, max_length=1000)
    signing_secret: str | None = Field(default=None, min_length=1, max_length=500)
    enabled: bool = True


class NotificationEndpointUpdate(BaseModel):
    provider: NotificationProvider | None = None
    url: str | None = Field(default=None, min_length=8, max_length=1000)
    signing_secret: str | None = Field(default=None, min_length=1, max_length=500)
    enabled: bool | None = None


class NotificationEndpointOut(BaseModel):
    id: int
    name: str
    provider: NotificationProvider
    url_configured: bool
    enabled: bool
    failure_count: int
    disabled_at: datetime | None
    last_delivery_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class AlertDeliveryOut(BaseModel):
    id: int
    event_id: int
    endpoint_id: int | None
    attempt: int
    status: Literal["pending", "sent", "failed"]
    response_status: int | None
    error: str | None
    attempted_at: datetime
    delivered_at: datetime | None
    next_attempt_at: datetime | None
    created_at: datetime


class DeliveryTestOut(BaseModel):
    sent: bool
    error: str | None = None


class AcknowledgeAllOut(BaseModel):
    acknowledged: int
