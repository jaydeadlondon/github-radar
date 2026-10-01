"""
Composite snapshot index for quality-filtered history reads

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28 00:00:00.000000

Every analytics read filters snapshots by ``repo_id``, ``quality_status`` and a
time window, but 0002 only indexed ``(repo_id, observed_at)``: SQLite still had
to touch rejected rows before discarding them.  The new covering index keeps the
hot path index-only as history grows.

The migration is additive and reversible; no data is touched.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_repo_snapshots_repo_quality_observed"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "repo_snapshots",
        ["repo_id", "quality_status", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="repo_snapshots")
