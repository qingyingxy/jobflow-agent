"""Preserve candidate corrections and resume import identity.

Revision ID: 0024_fact_provenance
Revises: 0023_education_records
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_fact_provenance"
down_revision = "0023_education_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, column in (
        ("user_profiles", "resume_import_state"),
        ("evidence_items", "provenance"),
    ):
        op.add_column(
            table,
            sa.Column(
                column, sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
        )


def downgrade() -> None:
    op.drop_column("evidence_items", "provenance")
    op.drop_column("user_profiles", "resume_import_state")
