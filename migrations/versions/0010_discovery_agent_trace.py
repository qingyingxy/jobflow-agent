"""Persist bounded discovery-agent tool decisions.

Revision ID: 0010_discovery_agent_trace
Revises: 0009_official_search_progress
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_discovery_agent_trace"
down_revision: str | None = "0009_official_search_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovery_runs",
        sa.Column(
            "agent_trace",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("discovery_runs", "agent_trace")
