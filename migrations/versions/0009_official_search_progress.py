"""Track official-site search intent and automatic top-five analysis progress.

Revision ID: 0009_official_search_progress
Revises: 0008_discovery_pool
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_official_search_progress"
down_revision: str | None = "0008_discovery_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("discovery_runs", sa.Column("search_query", sa.String(length=500)))
    op.add_column(
        "discovery_runs",
        sa.Column("max_results", sa.Integer(), nullable=False, server_default="20"),
    )
    op.add_column(
        "discovery_runs",
        sa.Column(
            "analysis_target_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "discovery_runs",
        sa.Column(
            "analysis_completed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "discovery_runs",
        sa.Column(
            "analysis_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "discovery_runs",
        sa.Column(
            "analysis_status",
            sa.String(length=24),
            nullable=False,
            server_default="NOT_REQUESTED",
        ),
    )


def downgrade() -> None:
    op.drop_column("discovery_runs", "analysis_status")
    op.drop_column("discovery_runs", "analysis_failure_count")
    op.drop_column("discovery_runs", "analysis_completed_count")
    op.drop_column("discovery_runs", "analysis_target_count")
    op.drop_column("discovery_runs", "max_results")
    op.drop_column("discovery_runs", "search_query")
