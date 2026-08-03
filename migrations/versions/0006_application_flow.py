"""Add candidate, application, and domain event records.

Revision ID: 0006_application_flow
Revises: 0005_job_analysis
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_application_flow"
down_revision: str | None = "0005_job_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_jobs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
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
        sa.UniqueConstraint(
            "user_id",
            "job_posting_id",
            name="uq_candidate_jobs_user_job_posting",
        ),
    )
    op.create_index("ix_candidate_jobs_user_id", "candidate_jobs", ["user_id"])
    op.create_index(
        "ix_candidate_jobs_job_posting_id",
        "candidate_jobs",
        ["job_posting_id"],
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("candidate_job_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("next_action", sa.String(length=240), nullable=True),
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
        "ix_applications_candidate_job_id",
        "applications",
        ["candidate_job_id"],
        unique=True,
    )

    op.create_table(
        "domain_events",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_domain_events_user_id", "domain_events", ["user_id"])
    op.create_index("ix_domain_events_entity_id", "domain_events", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_domain_events_entity_id", table_name="domain_events")
    op.drop_index("ix_domain_events_user_id", table_name="domain_events")
    op.drop_table("domain_events")
    op.drop_index(
        "ix_applications_candidate_job_id",
        table_name="applications",
    )
    op.drop_table("applications")
    op.drop_index(
        "ix_candidate_jobs_job_posting_id",
        table_name="candidate_jobs",
    )
    op.drop_index("ix_candidate_jobs_user_id", table_name="candidate_jobs")
    op.drop_table("candidate_jobs")
