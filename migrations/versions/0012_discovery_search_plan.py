"""Persist bounded discovery search plans.

Revision ID: 0012_discovery_search_plan
Revises: 0011_discovery_result_matches
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_discovery_search_plan"
down_revision: str | None = "0011_discovery_result_matches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovery_runs",
        sa.Column("search_plan", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discovery_runs", "search_plan")
