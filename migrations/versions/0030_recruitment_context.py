"""Keep associated recruitment batch evidence separate from original job text."""

import sqlalchemy as sa
from alembic import op

revision = "0030_recruitment_context"
down_revision = "0029_lead_retry_state"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "job_postings",
        sa.Column(
            "recruitment_context",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade():
    op.drop_column("job_postings", "recruitment_context")
