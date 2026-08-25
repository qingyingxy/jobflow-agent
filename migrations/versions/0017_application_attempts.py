"""Add manual application attempts, blockers, and submission receipts.

Revision ID: 0017_application_attempts
Revises: 0016_application_packets
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_application_attempts"
down_revision: str | None = "0016_application_packets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_attempts",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("packet_revision_id", sa.String(length=48), nullable=False),
        sa.Column("application_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
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
        sa.Column("form_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            "packet_revision_id",
            name="uq_application_attempts_application_revision",
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_application_attempts_user_idempotency",
        ),
    )
    for column in (
        "user_id",
        "application_id",
        "job_posting_id",
        "packet_revision_id",
    ):
        op.create_index(
            f"ix_application_attempts_{column}", "application_attempts", [column]
        )
    op.create_index(
        "ix_application_attempts_user_updated",
        "application_attempts",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "application_blockers",
        sa.Column("id", sa.String(length=56), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=48), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("observation", sa.String(length=2000), nullable=False),
        sa.Column("stop_reason", sa.String(length=1000), nullable=False),
        sa.Column(
            "retryable", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("next_strategy", sa.String(length=1000), nullable=True),
        sa.Column("required_user_action", sa.String(length=1000), nullable=True),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="OPEN"
        ),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
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
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "idempotency_key",
            name="uq_application_blockers_attempt_idempotency",
        ),
    )
    for column in ("user_id", "attempt_id", "application_id"):
        op.create_index(
            f"ix_application_blockers_{column}", "application_blockers", [column]
        )
    op.create_index(
        "ix_application_blockers_attempt_status",
        "application_blockers",
        ["attempt_id", "status"],
    )

    op.create_table(
        "submission_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=48), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("packet_revision_id", sa.String(length=48), nullable=False),
        sa.Column("confirmation_text", sa.String(length=4000), nullable=True),
        sa.Column("confirmation_url", sa.String(length=2048), nullable=True),
        sa.Column("application_number", sa.String(length=240), nullable=True),
        sa.Column(
            "screenshot_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "user_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_valid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "validation_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_submission_receipts_attempt"),
        sa.UniqueConstraint(
            "application_id", name="uq_submission_receipts_application"
        ),
        sa.UniqueConstraint("receipt_hash"),
    )
    for column in (
        "user_id",
        "attempt_id",
        "application_id",
        "packet_revision_id",
    ):
        op.create_index(
            f"ix_submission_receipts_{column}", "submission_receipts", [column]
        )


def downgrade() -> None:
    for column in (
        "packet_revision_id",
        "application_id",
        "attempt_id",
        "user_id",
    ):
        op.drop_index(
            f"ix_submission_receipts_{column}", table_name="submission_receipts"
        )
    op.drop_table("submission_receipts")

    op.drop_index(
        "ix_application_blockers_attempt_status", table_name="application_blockers"
    )
    for column in ("application_id", "attempt_id", "user_id"):
        op.drop_index(
            f"ix_application_blockers_{column}", table_name="application_blockers"
        )
    op.drop_table("application_blockers")

    op.drop_index(
        "ix_application_attempts_user_updated", table_name="application_attempts"
    )
    for column in (
        "packet_revision_id",
        "job_posting_id",
        "application_id",
        "user_id",
    ):
        op.drop_index(
            f"ix_application_attempts_{column}", table_name="application_attempts"
        )
    op.drop_table("application_attempts")

