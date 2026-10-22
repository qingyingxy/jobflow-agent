"""Persist bounded company searches and explicit continuation requests."""

import sqlalchemy as sa
from alembic import op

revision = "0027_company_search_progress"
down_revision = "0026_product_completion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("search_goals", sa.Column("company_search_state", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("discovery_runs", sa.Column("continued_company_id", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("discovery_runs", "continued_company_id")
    op.drop_column("search_goals", "company_search_state")
