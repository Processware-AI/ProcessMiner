"""plan mode: extend an existing document system with another standard

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_plan",
        sa.Column("mode", sa.String(length=8), server_default="new", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("generation_plan", "mode")
