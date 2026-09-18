# Commit 02 — feat: persist alert rules and events

Reference implementation commit: `f13756b5abc3f6a32992792ed73c78c9af29eff2`
Apply after: `Commit 01`

## Goal

Persist alert rules and alert events, including deduplication, retention relationships, indexes, and migration 0003.

## Files

### `alembic/versions/0003_alerts.py`

Create this file with the complete content below.

````python
"""add alert rules and events

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_rules_repo_id", "alert_rules", ["repo_id"])
    op.create_index(
        "ix_alert_rules_repo_id_enabled", "alert_rules", ["repo_id", "enabled"]
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("repo_id", sa.Integer(), nullable=True),
        sa.Column("repository_full_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "delivery_status",
            sa.String(length=24),
            server_default="inbox_only",
            nullable=False,
        ),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_id", "fingerprint", name="uq_alert_events_rule_fingerprint"
        ),
    )
    op.create_index(
        "ix_alert_events_acknowledged_created",
        "alert_events",
        ["acknowledged_at", "created_at"],
    )
    op.create_index("ix_alert_events_created_at", "alert_events", ["created_at"])
    op.create_index("ix_alert_events_repo_id", "alert_events", ["repo_id"])
    op.create_index("ix_alert_events_rule_id", "alert_events", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_events_rule_id", table_name="alert_events")
    op.drop_index("ix_alert_events_repo_id", table_name="alert_events")
    op.drop_index("ix_alert_events_created_at", table_name="alert_events")
    op.drop_index("ix_alert_events_acknowledged_created", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_index("ix_alert_rules_repo_id_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_repo_id", table_name="alert_rules")
    op.drop_table("alert_rules")
````

### `src/db/base.py`

Replace this file with the complete post-commit content below.

````python
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(settings.database_url)

if engine.url.get_backend_name() == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
````

### `src/db/models.py`

Replace this file with the complete post-commit content below.

````python
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("full_name", name="uq_repositories_full_name"),
        Index("ix_repositories_language", "language"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    html_url: Mapped[str] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(64))
    github_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    github_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    repository: Mapped["Repository"] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index("ix_repo_snapshots_repo_id_observed_at", "repo_id", "observed_at"),
    )


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        Index("ix_alert_rules_repo_id_enabled", "repo_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    threshold: Mapped[float | None] = mapped_column(Float)
    window_days: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_value: Mapped[float | None] = mapped_column(Float)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped["Repository"] = relationship(back_populates="alert_rules")
    events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="rule",
        passive_deletes=True,
    )


class AlertEvent(TimestampMixin, Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("rule_id", "fingerprint", name="uq_alert_events_rule_fingerprint"),
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
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str] = mapped_column(
        String(24), default="inbox_only", server_default="inbox_only"
    )
    delivery_error: Mapped[str | None] = mapped_column(Text)

    rule: Mapped["AlertRule | None"] = relationship(back_populates="events")
````

## Verify

```bash
ruff check src/alerts src/db/models.py src/db/base.py
```

## Commit

```bash
git add -- \
  alembic/versions/0003_alerts.py \
  src/db/base.py \
  src/db/models.py
git commit -m 'feat: persist alert rules and events'
```
