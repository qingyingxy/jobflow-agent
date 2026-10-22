"""Persist company search, extraction and verification independently."""
import sqlalchemy as sa
from alembic import op

revision = "0033_company_discovery_queue"
down_revision = "0032_body_review_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("company_discovery_tasks",
        sa.Column("goal_id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("goal_version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("lease_token", sa.String(40)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("company_discovery_tasks")
