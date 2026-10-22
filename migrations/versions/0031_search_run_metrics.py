"""Persist real search measurements separately from diagnostic traces."""
import sqlalchemy as sa
from alembic import op

revision = "0031_search_run_metrics"
down_revision = "0030_recruitment_context"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("discovery_runs", sa.Column("usage_metrics", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("discovery_runs", "usage_metrics")
