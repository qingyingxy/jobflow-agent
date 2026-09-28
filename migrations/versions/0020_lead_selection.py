"""Persist saved/ignored choices independently of verification status."""
import sqlalchemy as sa
from alembic import op

revision = "0020_lead_selection"
down_revision = "0019_ats_assistance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_leads", sa.Column("selection_status", sa.String(20), nullable=False, server_default="DISCOVERED"))


def downgrade():
    op.drop_column("job_leads", "selection_status")
