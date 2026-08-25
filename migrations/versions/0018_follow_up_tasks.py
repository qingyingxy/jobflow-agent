"""Add application follow-up tasks and calendar indexes.

Revision ID: 0018_follow_up_tasks
Revises: 0017_application_attempts
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_follow_up_tasks"
down_revision: str | None = "0017_application_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follow_up_tasks",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Shanghai",
        ),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "all_day", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("contact_name", sa.String(length=240), nullable=True),
        sa.Column("contact_detail", sa.String(length=500), nullable=True),
        sa.Column("channel", sa.String(length=80), nullable=True),
        sa.Column("next_action", sa.String(length=1000), nullable=False),
        sa.Column("notes", sa.String(length=4000), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="PENDING",
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_follow_up_tasks_user_idempotency",
        ),
        sa.UniqueConstraint(
            "user_id",
            "application_id",
            "event_type",
            "scheduled_at",
            "title",
            name="uq_follow_up_tasks_natural_identity",
        ),
    )
    for column in (
        "user_id",
        "application_id",
        "job_posting_id",
        "scheduled_at",
    ):
        op.create_index(
            f"ix_follow_up_tasks_{column}", "follow_up_tasks", [column]
        )
    op.create_index(
        "ix_follow_up_tasks_user_scheduled",
        "follow_up_tasks",
        ["user_id", "scheduled_at"],
    )
    op.create_index(
        "ix_follow_up_tasks_application_scheduled",
        "follow_up_tasks",
        ["application_id", "scheduled_at"],
    )
    op.create_index(
        "ix_follow_up_tasks_user_status_scheduled",
        "follow_up_tasks",
        ["user_id", "status", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_follow_up_tasks_user_status_scheduled", table_name="follow_up_tasks"
    )
    op.drop_index(
        "ix_follow_up_tasks_application_scheduled", table_name="follow_up_tasks"
    )
    op.drop_index(
        "ix_follow_up_tasks_user_scheduled", table_name="follow_up_tasks"
    )
    for column in (
        "scheduled_at",
        "job_posting_id",
        "application_id",
        "user_id",
    ):
        op.drop_index(
            f"ix_follow_up_tasks_{column}", table_name="follow_up_tasks"
        )
    op.drop_table("follow_up_tasks")

