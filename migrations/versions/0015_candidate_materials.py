"""Add private candidate profile and material library.

Revision ID: 0015_candidate_materials
Revises: 0014_job_availability_audit
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_candidate_materials"
down_revision: str | None = "0014_job_availability_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_private_profiles",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "contact_email_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("contact_email", sa.String(length=254), nullable=True),
        sa.Column(
            "contact_phone_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
        sa.Column(
            "current_status_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("current_status", sa.String(length=160), nullable=True),
        sa.Column(
            "availability_date_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("availability_date", sa.Date(), nullable=True),
        sa.Column(
            "work_authorization_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("work_authorization", sa.String(length=240), nullable=True),
        sa.Column(
            "sponsorship_required_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("sponsorship_required", sa.Boolean(), nullable=True),
        sa.Column(
            "salary_strategy_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("salary_strategy", sa.String(length=240), nullable=True),
        sa.Column(
            "relocation_willing_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing",
        ),
        sa.Column("relocation_willing", sa.Boolean(), nullable=True),
        sa.Column(
            "voluntary_disclosure_policy",
            sa.String(length=40),
            nullable=False,
            server_default="ask_each_time",
        ),
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
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "resume_assets",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=180), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=240), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
        sa.UniqueConstraint("user_id", "sha256", name="uq_resume_assets_user_hash"),
    )
    op.create_index("ix_resume_assets_user_id", "resume_assets", ["user_id"])

    op.create_table(
        "resume_versions",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=48), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("job_family", sa.String(length=120), nullable=True),
        sa.Column("source_version_id", sa.String(length=48), nullable=True),
        sa.Column("generation_reason", sa.String(length=240), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
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
            "user_id", "version_number", name="uq_resume_versions_user_number"
        ),
    )
    op.create_index("ix_resume_versions_user_id", "resume_versions", ["user_id"])
    op.create_index("ix_resume_versions_asset_id", "resume_versions", ["asset_id"])
    op.create_index(
        "ix_resume_versions_source_version_id",
        "resume_versions",
        ["source_version_id"],
    )

    op.create_table(
        "answer_bank_entries",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("question_pattern", sa.String(length=500), nullable=False),
        sa.Column(
            "normalized_question_pattern", sa.String(length=500), nullable=False
        ),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(length=32),
            nullable=False,
            server_default="general",
        ),
        sa.Column(
            "scope_value", sa.String(length=160), nullable=False, server_default=""
        ),
        sa.Column(
            "sensitivity",
            sa.String(length=32),
            nullable=False,
            server_default="standard",
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
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
            "user_id",
            "normalized_question_pattern",
            "scope_type",
            "scope_value",
            name="uq_answer_bank_user_question_scope",
        ),
    )
    op.create_index(
        "ix_answer_bank_entries_user_id", "answer_bank_entries", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_answer_bank_entries_user_id", table_name="answer_bank_entries")
    op.drop_table("answer_bank_entries")
    op.drop_index(
        "ix_resume_versions_source_version_id", table_name="resume_versions"
    )
    op.drop_index("ix_resume_versions_asset_id", table_name="resume_versions")
    op.drop_index("ix_resume_versions_user_id", table_name="resume_versions")
    op.drop_table("resume_versions")
    op.drop_index("ix_resume_assets_user_id", table_name="resume_assets")
    op.drop_table("resume_assets")
    op.drop_table("candidate_private_profiles")
