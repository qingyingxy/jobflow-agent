"""Persist private company candidates and official-entry evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0028_discovered_companies"
down_revision = "0027_company_search_progress"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discovered_companies",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("company", sa.String(100), nullable=False),
        sa.Column("homepage_url", sa.Text(), nullable=False),
        sa.Column("homepage_host", sa.String(253), nullable=False),
        sa.Column("career_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("discovered_query", sa.Text(), nullable=False),
        sa.Column("discovery_run_id", sa.String(40), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "homepage_host", name="uq_discovered_company_home"),
    )
    op.create_index("ix_discovered_companies_user_status", "discovered_companies", ["user_id", "status"])


def downgrade():
    op.drop_table("discovered_companies")
