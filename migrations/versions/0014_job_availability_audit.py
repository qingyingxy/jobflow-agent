"""Add audited job availability lifecycle.

Revision ID: 0014_job_availability_audit
Revises: 0013_trusted_job_leads
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_job_availability_audit"
down_revision: str | None = "0013_trusted_job_leads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column(
            "availability_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "job_postings",
        sa.Column(
            "last_availability_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "job_postings",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "job_availability_checks",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=24), nullable=False),
        sa.Column("result_status", sa.String(length=24), nullable=False),
        sa.Column("evidence_type", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_availability_checks_job_posting_id",
        "job_availability_checks",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_job_availability_checks_user_id",
        "job_availability_checks",
        ["user_id"],
    )
    op.create_index(
        "ix_job_availability_checks_job_checked",
        "job_availability_checks",
        ["job_posting_id", "checked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_availability_checks_job_checked",
        table_name="job_availability_checks",
    )
    op.drop_index(
        "ix_job_availability_checks_user_id",
        table_name="job_availability_checks",
    )
    op.drop_index(
        "ix_job_availability_checks_job_posting_id",
        table_name="job_availability_checks",
    )
    op.drop_table("job_availability_checks")
    op.drop_column("job_postings", "closed_at")
    op.drop_column("job_postings", "last_availability_checked_at")
    op.drop_column("job_postings", "availability_failure_count")
