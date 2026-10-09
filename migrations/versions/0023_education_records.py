"""Store separate education records without guessing a legacy history.

Revision ID: 0023_education_records
Revises: 0022_lead_extracted_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_education_records"
down_revision = "0022_lead_extracted_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "educations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )
    op.add_column(
        "user_profiles",
        sa.Column(
            "education_history_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "education_history_complete")
    op.drop_column("user_profiles", "educations")
