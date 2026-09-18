"""
Add composite snapshot index

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09 14:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Speed up history queries filtered by (repo, time window)."""
    op.create_index(
        "ix_repo_snapshots_repo_id_observed_at",
        "repo_snapshots",
        ["repo_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_repo_snapshots_repo_id_observed_at", table_name="repo_snapshots")
