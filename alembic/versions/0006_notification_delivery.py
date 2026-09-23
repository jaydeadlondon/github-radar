"""
Notification endpoints and delivery history

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-20 00:00:00.000000

The migration is additive. Existing alert events remain readable and keep their
legacy delivery status fields.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_endpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("signing_secret", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_notification_endpoints_name"),
    )
    op.create_index(
        "ix_notification_endpoints_enabled", "notification_endpoints", ["enabled"]
    )

    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["notification_endpoints.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["alert_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_deliveries_event_id", "alert_deliveries", ["event_id"])
    op.create_index(
        "ix_alert_deliveries_endpoint_id", "alert_deliveries", ["endpoint_id"]
    )
    op.create_index(
        "ix_alert_deliveries_event_created",
        "alert_deliveries",
        ["event_id", "created_at"],
    )
    op.create_index(
        "ix_alert_deliveries_status_next_attempt",
        "alert_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_alert_deliveries_status_next_attempt", table_name="alert_deliveries"
    )
    op.drop_index("ix_alert_deliveries_event_created", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_endpoint_id", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_event_id", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
    op.drop_index(
        "ix_notification_endpoints_enabled", table_name="notification_endpoints"
    )
    op.drop_table("notification_endpoints")
