"""Add discovery run and source metadata.

Revision ID: 0008_discovery_pool
Revises: 0007_resume_suggestions
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_discovery_pool"
down_revision: str | None = "0007_resume_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_postings", sa.Column("source_id", sa.String(length=100)))
    op.add_column("job_postings", sa.Column("source_job_id", sa.String(length=120)))
    op.add_column("job_postings", sa.Column("locations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("job_postings", sa.Column("job_type", sa.String(length=40)))
    op.add_column("job_postings", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("job_postings", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.create_index("ix_job_postings_source_id", "job_postings", ["source_id"])
    op.create_index("ix_job_postings_source_job_id", "job_postings", ["source_job_id"])
    op.create_index(
        "uq_job_postings_source_job",
        "job_postings",
        ["source_id", "source_job_id"],
        unique=True,
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovery_runs_user_id", "discovery_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_discovery_runs_user_id", table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_index("uq_job_postings_source_job", table_name="job_postings")
    op.drop_index("ix_job_postings_source_job_id", table_name="job_postings")
    op.drop_index("ix_job_postings_source_id", table_name="job_postings")
    op.drop_column("job_postings", "last_seen_at")
    op.drop_column("job_postings", "published_at")
    op.drop_column("job_postings", "job_type")
    op.drop_column("job_postings", "locations")
    op.drop_column("job_postings", "source_job_id")
    op.drop_column("job_postings", "source_id")
