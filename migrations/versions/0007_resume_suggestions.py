"""Add human-gated resume suggestions.

Revision ID: 0007_resume_suggestions
Revises: 0006_application_flow
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_resume_suggestions"
down_revision: str | None = "0006_application_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_suggestions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("job_analysis_id", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_label", sa.String(length=160), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("suggestion_text", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("agent_run_id", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resume_suggestions_user_id", "resume_suggestions", ["user_id"])
    op.create_index(
        "ix_resume_suggestions_application_id",
        "resume_suggestions",
        ["application_id"],
    )
    op.create_index(
        "ix_resume_suggestions_job_analysis_id",
        "resume_suggestions",
        ["job_analysis_id"],
    )
    op.create_index(
        "ix_resume_suggestions_agent_run_id",
        "resume_suggestions",
        ["agent_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resume_suggestions_agent_run_id",
        table_name="resume_suggestions",
    )
    op.drop_index(
        "ix_resume_suggestions_job_analysis_id",
        table_name="resume_suggestions",
    )
    op.drop_index(
        "ix_resume_suggestions_application_id",
        table_name="resume_suggestions",
    )
    op.drop_index("ix_resume_suggestions_user_id", table_name="resume_suggestions")
    op.drop_table("resume_suggestions")
