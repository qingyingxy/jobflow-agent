"""Add user-scoped job analysis results.

Revision ID: 0005_job_analysis
Revises: 0004_agent_runs
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_job_analysis"
down_revision: str | None = "0004_agent_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_analyses",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("parse_result_id", sa.String(length=40), nullable=False),
        sa.Column("analysis_version", sa.String(length=80), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("eligibility", sa.JSON(), nullable=False),
        sa.Column("matches", sa.JSON(), nullable=False),
        sa.Column("score", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("missing_information", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_analyses_user_id", "job_analyses", ["user_id"])
    op.create_index(
        "ix_job_analyses_job_posting_id",
        "job_analyses",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_job_analyses_parse_result_id",
        "job_analyses",
        ["parse_result_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_analyses_parse_result_id", table_name="job_analyses")
    op.drop_index("ix_job_analyses_job_posting_id", table_name="job_analyses")
    op.drop_index("ix_job_analyses_user_id", table_name="job_analyses")
    op.drop_table("job_analyses")
