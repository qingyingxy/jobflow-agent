"""Persist verification retry methods, limits and cooldowns across search runs."""
import sqlalchemy as sa
from alembic import op

revision = "0029_lead_retry_state"
down_revision = "0028_discovered_companies"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_leads", sa.Column("retry_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("job_leads", "retry_state")
