"""document retire: retire documents that were ever approved instead of deleting them

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 승인판은 지울 수 없으므로(document_revision_guard), 승인된 적 있는 문서는 폐지로 남긴다.
    op.add_column("document", sa.Column("retired_at", sa.DateTime(timezone=True)))
    op.add_column(
        "document",
        sa.Column(
            "retired_by",
            UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "document",
        sa.Column("retire_reason", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("document", "retire_reason")
    op.drop_column("document", "retired_by")
    op.drop_column("document", "retired_at")
