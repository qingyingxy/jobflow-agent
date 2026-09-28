"""Keep extracted preview facts separate from verified jobs and original hints."""
import sqlalchemy as sa
from alembic import op

revision = "0022_lead_extracted_fields"
down_revision = "0021_search_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_leads", sa.Column("extracted_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("job_leads", "extracted_fields")
