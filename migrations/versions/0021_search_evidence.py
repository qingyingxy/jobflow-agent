"""Preserve full search responses and independent-query metrics."""

import sqlalchemy as sa
from alembic import op

revision = "0021_search_evidence"
down_revision = "0020_lead_selection"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_evidence",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("discovery_run_id", sa.String(40), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_search_evidence_user_id", "search_evidence", ["user_id"])
    op.create_index(
        "ix_search_evidence_discovery_run_id", "search_evidence", ["discovery_run_id"]
    )


def downgrade():
    op.drop_table("search_evidence")
