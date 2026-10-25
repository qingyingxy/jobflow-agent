"""Independent, resumable company discovery for campus browsing."""
import sqlalchemy as sa
from alembic import op

revision = "0036_campaign_discovery"
down_revision = "0035_recruitment_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("campaign_discovery_tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("lease_token", sa.String(40)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "year"))
    op.create_index("ix_campaign_discovery_tasks_user_id", "campaign_discovery_tasks", ["user_id"])
    op.create_index("ix_campaign_discovery_due", "campaign_discovery_tasks", ["status", "next_run_at"])


def downgrade():
    op.drop_table("campaign_discovery_tasks")
