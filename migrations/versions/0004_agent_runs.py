"""Add job parse results and agent run audit records.

Revision ID: 0004_agent_runs
Revises: 0003_job_postings
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agent_runs"
down_revision: str | None = "0003_job_postings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_parse_results",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("structured_jd", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_parse_results_job_posting_id",
        "job_parse_results",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_job_parse_results_content_hash",
        "job_parse_results",
        ["content_hash"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("run_type", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("validation_status", sa.String(length=24), nullable=False),
        sa.Column("validation_result", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_run_type", "agent_runs", ["run_type"])
    op.create_index("ix_agent_runs_target_id", "agent_runs", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_target_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_run_type", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index(
        "ix_job_parse_results_content_hash",
        table_name="job_parse_results",
    )
    op.drop_index(
        "ix_job_parse_results_job_posting_id",
        table_name="job_parse_results",
    )
    op.drop_table("job_parse_results")
