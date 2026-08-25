"""Add trusted job leads and posting verification metadata.

Revision ID: 0013_trusted_job_leads
Revises: 0012_discovery_search_plan
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_trusted_job_leads"
down_revision: str | None = "0012_discovery_search_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="LEGACY_UNVERIFIED",
        ),
    )
    op.add_column(
        "job_postings",
        sa.Column(
            "availability_status",
            sa.String(length=24),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.add_column(
        "job_postings",
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE job_postings
        SET verification_status = CASE
                WHEN source_type = 'company_adapter' THEN 'VERIFIED_OFFICIAL'
                WHEN source_type = 'manual_text' THEN 'USER_PROVIDED'
                ELSE 'LEGACY_UNVERIFIED'
            END,
            availability_status = CASE
                WHEN source_type = 'company_adapter' THEN 'ACTIVE'
                ELSE 'UNKNOWN'
            END,
            first_seen_at = COALESCE(last_seen_at, retrieved_at, created_at),
            last_verified_at = CASE
                WHEN source_type = 'company_adapter'
                THEN COALESCE(last_seen_at, retrieved_at)
                ELSE NULL
            END
        """
    )

    op.create_table(
        "job_leads",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("discovery_run_id", sa.String(length=40), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=True),
        sa.Column("source_job_id", sa.String(length=120), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("company_hint", sa.String(length=160), nullable=True),
        sa.Column("title_hint", sa.String(length=160), nullable=True),
        sa.Column("search_snippet", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("job_posting_id", sa.String(length=40), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discovery_run_id",
            "source_id",
            "source_job_id",
            name="uq_job_leads_run_source_job",
        ),
    )
    op.create_index("ix_job_leads_discovery_run_id", "job_leads", ["discovery_run_id"])
    op.create_index("ix_job_leads_user_id", "job_leads", ["user_id"])
    op.create_index("ix_job_leads_job_posting_id", "job_leads", ["job_posting_id"])
    op.create_index("ix_job_leads_user_status", "job_leads", ["user_id", "status"])

    op.create_table(
        "lead_verifications",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("lead_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "field_evidence",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_verifications_lead_id", "lead_verifications", ["lead_id"])
    op.create_index("ix_lead_verifications_user_id", "lead_verifications", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_verifications_user_id", table_name="lead_verifications")
    op.drop_index("ix_lead_verifications_lead_id", table_name="lead_verifications")
    op.drop_table("lead_verifications")
    op.drop_index("ix_job_leads_user_status", table_name="job_leads")
    op.drop_index("ix_job_leads_job_posting_id", table_name="job_leads")
    op.drop_index("ix_job_leads_user_id", table_name="job_leads")
    op.drop_index("ix_job_leads_discovery_run_id", table_name="job_leads")
    op.drop_table("job_leads")
    op.drop_column("job_postings", "last_verified_at")
    op.drop_column("job_postings", "first_seen_at")
    op.drop_column("job_postings", "availability_status")
    op.drop_column("job_postings", "verification_status")
