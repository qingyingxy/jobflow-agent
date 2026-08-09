"""Persist query-specific strict and expanded discovery results.

Revision ID: 0011_discovery_result_matches
Revises: 0010_discovery_agent_trace
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_discovery_result_matches"
down_revision: str | None = "0010_discovery_agent_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovery_runs",
        sa.Column(
            "result_matches",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("discovery_runs", "result_matches")
