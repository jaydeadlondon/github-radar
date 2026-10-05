from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )


class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("full_name", name="uq_repositories_full_name"),
        Index("ix_repositories_language", "language"),
        Index("ix_repositories_tracking_enabled", "tracking_enabled"),
        Index("ix_repositories_tracking_paused", "tracking_paused"),
        Index("ix_repositories_tracking_label", "tracking_label"),
        Index("ix_repositories_last_snapshot_attempt", "last_snapshot_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    html_url: Mapped[str] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(64))
    github_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    github_pushed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    default_branch: Mapped[str | None] = mapped_column(String(255))
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    tracking_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    tracking_paused: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    tracking_label: Mapped[str | None] = mapped_column(String(100))
    last_successful_snapshot_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_snapshot_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_snapshot_error: Mapped[str | None] = mapped_column(Text)
    next_snapshot_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    snapshots: Mapped[list["RepoSnapshot"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )

    alert_rules: Mapped[list["AlertRule"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )


class RepoSnapshot(TimestampMixin, Base):
    __tablename__ = "repo_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    stargazers_count: Mapped[int] = mapped_column(Integer, default=0)
    forks_count: Mapped[int] = mapped_column(Integer, default=0)
    open_issues_count: Mapped[int] = mapped_column(Integer, default=0)
    observed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), index=True
    )

    quality_status: Mapped[str] = mapped_column(
        String(24), default="accepted", server_default="accepted", nullable=False
    )
    quality_reason: Mapped[str | None] = mapped_column(String(128))

    repository: Mapped["Repository"] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index("ix_repo_snapshots_repo_id_observed_at", "repo_id", "observed_at"),
        Index("ix_repo_snapshots_quality_status", "quality_status"),
        Index(
            "ix_repo_snapshots_repo_quality_observed",
            "repo_id",
            "quality_status",
            "observed_at",
        ),
    )


class JobLock(Base):
    __tablename__ = "job_locks"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (Index("ix_job_locks_expires_at", "expires_at"),)


class SnapshotJob(TimestampMixin, Base):
    __tablename__ = "snapshot_jobs"
    __table_args__ = (
        Index("ix_snapshot_jobs_status_started", "status", "started_at"),
        Index("ix_snapshot_jobs_job_type_started", "job_type", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    total_repositories: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded_repositories: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    failed_repositories: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rules_repo_id_enabled", "repo_id", "enabled"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    threshold: Mapped[float | None] = mapped_column(Float)
    window_days: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_value: Mapped[float | None] = mapped_column(Float)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    repository: Mapped["Repository"] = relationship(back_populates="alert_rules")
    events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="rule",
        passive_deletes=True,
    )


class NotificationEndpoint(TimestampMixin, Base):
    __tablename__ = "notification_endpoints"
    __table_args__ = (
        UniqueConstraint("name", name="uq_notification_endpoints_name"),
        Index("ix_notification_endpoints_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), default="generic", nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    signing_secret: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    disabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_delivery_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)

    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="endpoint",
        passive_deletes=True,
    )


class AlertEvent(TimestampMixin, Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint(
            "rule_id", "fingerprint", name="uq_alert_events_rule_fingerprint"
        ),
        Index("ix_alert_events_created_at", "created_at"),
        Index("ix_alert_events_acknowledged_created", "acknowledged_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="SET NULL"), index=True
    )
    repo_id: Mapped[int | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"), index=True
    )
    repository_full_name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    current_value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delivery_status: Mapped[str] = mapped_column(
        String(24), default="inbox_only", server_default="inbox_only"
    )
    delivery_error: Mapped[str | None] = mapped_column(Text)

    rule: Mapped["AlertRule | None"] = relationship(back_populates="events")
    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
    )


class AlertDelivery(TimestampMixin, Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (
        Index("ix_alert_deliveries_event_created", "event_id", "created_at"),
        Index("ix_alert_deliveries_status_next_attempt", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("alert_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_id: Mapped[int | None] = mapped_column(
        ForeignKey("notification_endpoints.id", ondelete="SET NULL"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    response_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    event: Mapped["AlertEvent"] = relationship(back_populates="deliveries")
    endpoint: Mapped["NotificationEndpoint | None"] = relationship(
        back_populates="deliveries"
    )
