"""Add frozen, reviewable application packets.

Revision ID: 0016_application_packets
Revises: 0015_candidate_materials
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_application_packets"
down_revision: str | None = "0015_candidate_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "application_packets",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("current_revision_id", sa.String(length=48), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="DRAFT",
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id", name="uq_application_packets_application"
        ),
    )
    op.create_index(
        "ix_application_packets_user_id", "application_packets", ["user_id"]
    )
    op.create_index(
        "ix_application_packets_job_posting_id",
        "application_packets",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_application_packets_user_updated",
        "application_packets",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "packet_revisions",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("packet_id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("job_posting_id", sa.String(length=40), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("supersedes_revision_id", sa.String(length=48), nullable=True),
        sa.Column("job_analysis_id", sa.String(length=40), nullable=False),
        sa.Column("analysis_version", sa.String(length=80), nullable=False),
        sa.Column("analysis_input_hash", sa.String(length=64), nullable=False),
        sa.Column("jd_content_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("resume_version_id", sa.String(length=48), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("job_snapshot", sa.JSON(), nullable=False),
        sa.Column("analysis_snapshot", sa.JSON(), nullable=False),
        sa.Column("profile_snapshot", sa.JSON(), nullable=False),
        sa.Column("resume_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "evidence_snapshots",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "form_answer_snapshots",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "open_questions",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "risk_snapshots",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "confirmation_items",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "blockers",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_by_actor",
            sa.String(length=24),
            nullable=False,
            server_default="user",
        ),
        *_timestamps(),
        sa.Column(
            "submitted_for_review_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "packet_id",
            "revision_number",
            name="uq_packet_revisions_packet_number",
        ),
    )
    for column in (
        "packet_id",
        "user_id",
        "application_id",
        "job_posting_id",
        "supersedes_revision_id",
        "job_analysis_id",
        "resume_version_id",
    ):
        op.create_index(
            f"ix_packet_revisions_{column}", "packet_revisions", [column]
        )
    op.create_index(
        "ix_packet_revisions_packet_created",
        "packet_revisions",
        ["packet_id", "created_at"],
    )

    op.create_table(
        "packet_decisions",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("packet_id", sa.String(length=48), nullable=False),
        sa.Column("revision_id", sa.String(length=48), nullable=False),
        sa.Column("application_id", sa.String(length=40), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id",
            "decision",
            name="uq_packet_decisions_revision_decision",
        ),
    )
    for column in (
        "user_id",
        "packet_id",
        "revision_id",
        "application_id",
    ):
        op.create_index(
            f"ix_packet_decisions_{column}", "packet_decisions", [column]
        )


def downgrade() -> None:
    for column in (
        "application_id",
        "revision_id",
        "packet_id",
        "user_id",
    ):
        op.drop_index(
            f"ix_packet_decisions_{column}", table_name="packet_decisions"
        )
    op.drop_table("packet_decisions")

    op.drop_index(
        "ix_packet_revisions_packet_created", table_name="packet_revisions"
    )
    for column in (
        "resume_version_id",
        "job_analysis_id",
        "supersedes_revision_id",
        "job_posting_id",
        "application_id",
        "user_id",
        "packet_id",
    ):
        op.drop_index(
            f"ix_packet_revisions_{column}", table_name="packet_revisions"
        )
    op.drop_table("packet_revisions")

    op.drop_index(
        "ix_application_packets_user_updated", table_name="application_packets"
    )
    op.drop_index(
        "ix_application_packets_job_posting_id", table_name="application_packets"
    )
    op.drop_index(
        "ix_application_packets_user_id", table_name="application_packets"
    )
    op.drop_table("application_packets")
