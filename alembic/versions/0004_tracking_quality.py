"""
Managed tracking state and snapshot quality metadata

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18 00:00:00.000000

The migration is additive. Existing repository rows stay tracked and existing
snapshot rows are accepted so upgrading a v0.7 database preserves behaviour.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("repositories") as batch:
        batch.add_column(
            sa.Column("default_branch", sa.String(length=255), nullable=True)
        )
        batch.add_column(
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "tracking_enabled",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "tracking_paused",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("tracking_label", sa.String(length=100), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "last_successful_snapshot_at", sa.DateTime(timezone=True), nullable=True
            )
        )
        batch.add_column(
            sa.Column(
                "last_snapshot_attempt_at", sa.DateTime(timezone=True), nullable=True
            )
        )
        batch.add_column(sa.Column("last_snapshot_error", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("next_snapshot_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("repo_snapshots") as batch:
        batch.add_column(
            sa.Column(
                "quality_status",
                sa.String(length=24),
                server_default=sa.text("'accepted'"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("quality_reason", sa.String(length=128), nullable=True)
        )

    op.execute("""
        UPDATE repositories
        SET last_successful_snapshot_at = (
            SELECT MAX(observed_at) FROM repo_snapshots
            WHERE repo_snapshots.repo_id = repositories.id
              AND repo_snapshots.quality_status IN ('accepted', 'anomalous')
        ),
        last_snapshot_attempt_at = (
            SELECT MAX(observed_at) FROM repo_snapshots
            WHERE repo_snapshots.repo_id = repositories.id
              AND repo_snapshots.quality_status IN ('accepted', 'anomalous')
        )
        WHERE EXISTS (
            SELECT 1 FROM repo_snapshots
            WHERE repo_snapshots.repo_id = repositories.id
        )
        """)

    op.create_index(
        "ix_repositories_tracking_enabled", "repositories", ["tracking_enabled"]
    )
    op.create_index(
        "ix_repositories_tracking_paused", "repositories", ["tracking_paused"]
    )
    op.create_index(
        "ix_repositories_tracking_label", "repositories", ["tracking_label"]
    )
    op.create_index(
        "ix_repositories_last_snapshot_attempt",
        "repositories",
        ["last_snapshot_attempt_at"],
    )
    op.create_index(
        "ix_repo_snapshots_quality_status", "repo_snapshots", ["quality_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_repo_snapshots_quality_status", table_name="repo_snapshots")
    op.drop_index("ix_repositories_last_snapshot_attempt", table_name="repositories")
    op.drop_index("ix_repositories_tracking_label", table_name="repositories")
    op.drop_index("ix_repositories_tracking_paused", table_name="repositories")
    op.drop_index("ix_repositories_tracking_enabled", table_name="repositories")

    with op.batch_alter_table("repo_snapshots") as batch:
        batch.drop_column("quality_reason")
        batch.drop_column("quality_status")

    with op.batch_alter_table("repositories") as batch:
        batch.drop_column("next_snapshot_at")
        batch.drop_column("last_snapshot_error")
        batch.drop_column("last_snapshot_attempt_at")
        batch.drop_column("last_successful_snapshot_at")
        batch.drop_column("tracking_label")
        batch.drop_column("tracking_paused")
        batch.drop_column("tracking_enabled")
        batch.drop_column("archived_at")
        batch.drop_column("default_branch")
