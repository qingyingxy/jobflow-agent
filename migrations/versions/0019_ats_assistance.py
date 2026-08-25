"""Add limited ATS assistance sessions and one-time authorizations.

Revision ID: 0019_ats_assistance
Revises: 0018_follow_up_tasks
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_ats_assistance"
down_revision: str | None = "0018_follow_up_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ats_assistance_sessions",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=48), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("packet_revision_id", sa.String(length=48), nullable=False),
        sa.Column("application_url", sa.String(length=2048), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="INSPECTED"),
        sa.Column("page_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("field_plan", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("field_confirmations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("handoff_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("final_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("current_authorization_id", sa.String(length=48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id"),
    )
    for column in (
        "user_id",
        "attempt_id",
        "application_id",
        "job_posting_id",
        "packet_revision_id",
        "current_authorization_id",
    ):
        op.create_index(f"ix_ats_assistance_sessions_{column}", "ats_assistance_sessions", [column])
    op.create_index(
        "ix_ats_sessions_user_updated",
        "ats_assistance_sessions",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "ats_submission_authorizations",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=48), nullable=False),
        sa.Column("attempt_id", sa.String(length=48), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("packet_revision_id", sa.String(length=48), nullable=False),
        sa.Column("application_url_hash", sa.String(length=64), nullable=False),
        sa.Column("page_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_hash", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    for column in (
        "user_id",
        "session_id",
        "attempt_id",
        "job_posting_id",
        "packet_revision_id",
        "token_hash",
    ):
        op.create_index(
            f"ix_ats_submission_authorizations_{column}",
            "ats_submission_authorizations",
            [column],
        )
    op.create_index(
        "ix_ats_authorizations_session_created",
        "ats_submission_authorizations",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ats_authorizations_session_created", table_name="ats_submission_authorizations")
    for column in (
        "token_hash",
        "packet_revision_id",
        "job_posting_id",
        "attempt_id",
        "session_id",
        "user_id",
    ):
        op.drop_index(
            f"ix_ats_submission_authorizations_{column}",
            table_name="ats_submission_authorizations",
        )
    op.drop_table("ats_submission_authorizations")

    op.drop_index("ix_ats_sessions_user_updated", table_name="ats_assistance_sessions")
    for column in (
        "current_authorization_id",
        "packet_revision_id",
        "job_posting_id",
        "application_id",
        "attempt_id",
        "user_id",
    ):
        op.drop_index(
            f"ix_ats_assistance_sessions_{column}",
            table_name="ats_assistance_sessions",
        )
    op.drop_table("ats_assistance_sessions")
