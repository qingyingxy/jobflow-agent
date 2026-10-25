"""Company recruitment announcements and hourly watches."""
import sqlalchemy as sa
from alembic import op

revision = "0035_recruitment_campaigns"
down_revision = "0034_portal_tracking"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("campaign_watches",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("company_id", sa.String(100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("followed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("succeeded_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(40)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(300)),
        sa.Column("cache", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "company_id", "year"))
    op.create_index("ix_campaign_watches_user_id", "campaign_watches", ["user_id"])
    op.create_index("ix_campaign_watch_due", "campaign_watches", ["status", "next_check_at"])
    op.create_table("recruitment_campaigns",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("company_id", sa.String(100), nullable=False),
        sa.Column("company", sa.String(160), nullable=False),
        sa.Column("identity", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("batch", sa.String(30), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "company_id", "identity"))
    op.create_index("ix_recruitment_campaigns_user_id", "recruitment_campaigns", ["user_id"])
    op.create_table("campaign_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("campaign_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False))
    op.create_index("ix_campaign_events_user_id", "campaign_events", ["user_id"])
    op.create_index("ix_campaign_events_campaign_id", "campaign_events", ["campaign_id"])


def downgrade():
    op.drop_table("campaign_events")
    op.drop_table("recruitment_campaigns")
    op.drop_table("campaign_watches")
