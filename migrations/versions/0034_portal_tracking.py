"""Keep original website application statuses and change history."""
import sqlalchemy as sa
from alembic import op

revision = "0034_portal_tracking"
down_revision = "0033_company_discovery_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("portal_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("company", sa.String(100), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("error", sa.String(300)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("succeeded_at", sa.DateTime(timezone=True)),
        sa.Column("sync_token", sa.String(64)),
        sa.Column("sync_started_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "url"))
    op.create_index("ix_portal_sources_user_id", "portal_sources", ["user_id"])
    op.create_table("portal_records",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("identity", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("recruitment_type", sa.String(100), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("submitted_at_text", sa.String(40), nullable=False),
        sa.Column("raw_status", sa.String(100), nullable=False),
        sa.Column("application_id", sa.String(40), unique=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "identity"))
    op.create_index("ix_portal_records_source_id", "portal_records", ["source_id"])
    op.create_table("portal_observations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("record_id", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_status", sa.String(100)),
        sa.Column("raw_status", sa.String(100), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False))
    op.create_index("ix_portal_observations_record_id", "portal_observations", ["record_id"])


def downgrade():
    op.drop_table("portal_observations")
    op.drop_table("portal_records")
    op.drop_table("portal_sources")
