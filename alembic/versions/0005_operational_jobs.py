"""
Worker locks and snapshot job state

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-20 00:00:00.000000

The migration is additive and does not alter repository or snapshot history.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_locks",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index("ix_job_locks_expires_at", "job_locks", ["expires_at"])

    op.create_table(
        "snapshot_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "total_repositories", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "succeeded_repositories", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "failed_repositories", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_snapshot_jobs_status_started",
        "snapshot_jobs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_snapshot_jobs_job_type_started",
        "snapshot_jobs",
        ["job_type", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_snapshot_jobs_job_type_started", table_name="snapshot_jobs")
    op.drop_index("ix_snapshot_jobs_status_started", table_name="snapshot_jobs")
    op.drop_table("snapshot_jobs")
    op.drop_index("ix_job_locks_expires_at", table_name="job_locks")
    op.drop_table("job_locks")
