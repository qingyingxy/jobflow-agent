"""Saved search goals and immutable execution snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0025_search_goals"
down_revision = "0024_fact_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_goals",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("condition_sources", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("company_ids", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_search_goals_user_updated", "search_goals", ["user_id", "updated_at"]
    )
    op.add_column(
        "discovery_runs", sa.Column("search_goal_id", sa.String(40), nullable=True)
    )
    op.create_index(
        "ix_discovery_runs_search_goal_id", "discovery_runs", ["search_goal_id"]
    )
    op.add_column(
        "discovery_runs", sa.Column("search_goal_version", sa.Integer(), nullable=True)
    )
    op.add_column(
        "discovery_runs", sa.Column("goal_conditions", sa.JSON(), nullable=True)
    )
    op.add_column(
        "discovery_runs", sa.Column("library_baseline", sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_index("ix_discovery_runs_search_goal_id", table_name="discovery_runs")
    for name in (
        "search_goal_id",
        "search_goal_version",
        "goal_conditions",
        "library_baseline",
    ):
        op.drop_column("discovery_runs", name)
    op.drop_table("search_goals")
