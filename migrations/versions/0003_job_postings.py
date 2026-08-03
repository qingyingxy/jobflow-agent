"""Create imported job postings.

Revision ID: 0003_job_postings
Revises: 0002_profile_evidence
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_job_postings"
down_revision: str | None = "0002_profile_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "source_type",
            sa.String(length=40),
            server_default=sa.text("'manual_text'"),
            nullable=False,
        ),
        sa.Column("company", sa.String(length=160), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
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
    op.create_index(
        "ix_job_postings_content_hash",
        "job_postings",
        ["content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_postings_content_hash", table_name="job_postings")
    op.drop_table("job_postings")
