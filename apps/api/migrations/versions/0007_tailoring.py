"""tailoring: child systems override or exclude inherited documents

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 하위 체계가 상위 문서를 대체할 때: 어느 문서를 대체했고, 상위의 어느 판을 기준으로 삼았는지.
    op.add_column("document", sa.Column("overrides_id", sa.UUID(), nullable=True))
    op.add_column("document", sa.Column("base_revision_id", sa.UUID(), nullable=True))
    op.add_column(
        "document",
        sa.Column("tailoring_reason", sa.Text(), server_default="", nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_document_overrides_id_document"),
        "document",
        "document",
        ["overrides_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_document_base_revision_id_document_revision"),
        "document",
        "document_revision",
        ["base_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # 한 체계에서 같은 상위 문서를 두 번 대체할 수 없다.
    op.create_index(
        "uq_document_override",
        "document",
        ["system_id", "overrides_id"],
        unique=True,
        postgresql_where=sa.text("overrides_id IS NOT NULL"),
    )

    op.create_table(
        "document_exclusion",
        sa.Column("system_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("excluded_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["process_system.id"],
            name=op.f("fk_document_exclusion_system_id_process_system"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name=op.f("fk_document_exclusion_document_id_document"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_document_exclusion_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["excluded_by"],
            ["app_user.id"],
            name=op.f("fk_document_exclusion_excluded_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("system_id", "document_id", name=op.f("pk_document_exclusion")),
    )
    op.create_index(
        op.f("ix_document_exclusion_tenant_id"), "document_exclusion", ["tenant_id"], unique=False
    )
    op.execute("ALTER TABLE document_exclusion ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON document_exclusion
          USING (tenant_id = app_current_tenant())
          WITH CHECK (tenant_id = app_current_tenant());
        """
    )


def downgrade() -> None:
    op.drop_table("document_exclusion")
    op.drop_index("uq_document_override", table_name="document")
    op.drop_constraint(
        op.f("fk_document_base_revision_id_document_revision"), "document", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_document_overrides_id_document"), "document", type_="foreignkey")
    op.drop_column("document", "tailoring_reason")
    op.drop_column("document", "base_revision_id")
    op.drop_column("document", "overrides_id")
