"""Consent-bound resume cache and user JD corrections."""

import sqlalchemy as sa
from alembic import op

revision = "0026_product_completion"
down_revision = "0025_search_goals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("search_goals", sa.Column("update_interval_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("search_goals", sa.Column("next_update_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("search_goals", sa.Column("schedule_error", sa.String(200), nullable=True))
    op.add_column("resume_assets", sa.Column("parse_cache", sa.JSON(), nullable=True))
    op.add_column("job_analyses", sa.Column("structured_jd", sa.JSON(), nullable=True))
    op.create_table(
        "job_corrections",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("job_posting_id", sa.String(40), nullable=False),
        sa.Column("parse_result_id", sa.String(40), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=True),
        sa.Column("structured_jd", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "job_posting_id", "revision"),
    )
    op.create_index("ix_job_corrections_user_id", "job_corrections", ["user_id"])
    op.create_index("ix_job_corrections_job_posting_id", "job_corrections", ["job_posting_id"])


def downgrade():
    for column in ("schedule_error", "next_update_at", "update_interval_minutes"):
        op.drop_column("search_goals", column)
    op.drop_table("job_corrections")
    op.drop_column("job_analyses", "structured_jd")
    op.drop_column("resume_assets", "parse_cache")
