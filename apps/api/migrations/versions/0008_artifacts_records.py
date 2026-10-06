"""artifacts and records: harmonize existing deliverables into standard records

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TENANT_TABLES = ["artifact", "artifact_text", "process_record"]


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["app_user.id"], name=op.f(f"fk_{table}_{column}_app_user"), ondelete="SET NULL"
    )


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenant.id"], name=op.f(f"fk_{table}_tenant_id_tenant"), ondelete="CASCADE"
    )


def _system_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["system_id"],
        ["process_system.id"],
        name=op.f(f"fk_{table}_system_id_process_system"),
        ondelete="CASCADE",
    )


def _now() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "artifact",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("system_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=True),
        sa.Column("match_state", sa.String(length=12), nullable=False),
        sa.Column("template_document_id", sa.UUID(), nullable=True),
        sa.Column("match_confidence", sa.Integer(), nullable=True),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confirmed_by", sa.UUID(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        _now(),
        _tenant_fk("artifact"),
        _system_fk("artifact"),
        sa.ForeignKeyConstraint(
            ["template_document_id"],
            ["document.id"],
            name=op.f("fk_artifact_template_document_id_document"),
            ondelete="SET NULL",
        ),
        _user_fk("artifact", "confirmed_by"),
        _user_fk("artifact", "uploaded_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact")),
        sa.UniqueConstraint("system_id", "sha256", name=op.f("uq_artifact_system_id")),
    )
    op.create_index(op.f("ix_artifact_system_id"), "artifact", ["system_id"], unique=False)
    op.create_index(op.f("ix_artifact_tenant_id"), "artifact", ["tenant_id"], unique=False)

    op.create_table(
        "artifact_text",
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("segments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifact.id"],
            name=op.f("fk_artifact_text_artifact_id_artifact"),
            ondelete="CASCADE",
        ),
        _tenant_fk("artifact_text"),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_artifact_text")),
    )
    op.create_index(
        op.f("ix_artifact_text_tenant_id"), "artifact_text", ["tenant_id"], unique=False
    )

    op.create_table(
        "process_record",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("system_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("template_document_id", sa.UUID(), nullable=False),
        sa.Column("template_revision_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=True),
        sa.Column("legacy", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("generated_by", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        _now(),
        sa.Column("published_by", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        _tenant_fk("process_record"),
        _system_fk("process_record"),
        sa.ForeignKeyConstraint(
            ["template_document_id"],
            ["document.id"],
            name=op.f("fk_process_record_template_document_id_document"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_revision_id"],
            ["document_revision.id"],
            name=op.f("fk_process_record_template_revision_id_document_revision"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifact.id"],
            name=op.f("fk_process_record_artifact_id_artifact"),
            ondelete="SET NULL",
        ),
        _user_fk("process_record", "created_by"),
        _user_fk("process_record", "published_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_process_record")),
        sa.UniqueConstraint("system_id", "code", name=op.f("uq_process_record_system_id")),
    )
    op.create_index(
        op.f("ix_process_record_system_id"), "process_record", ["system_id"], unique=False
    )
    op.create_index(
        op.f("ix_process_record_tenant_id"), "process_record", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_process_record_artifact",
        "process_record",
        ["artifact_id"],
        unique=True,
        postgresql_where=sa.text("artifact_id IS NOT NULL"),
    )

    op.add_column("run", sa.Column("artifact_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_run_artifact_id"), "run", ["artifact_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_run_artifact_id_artifact"),
        "run",
        "artifact",
        ["artifact_id"],
        ["id"],
        ondelete="CASCADE",
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = app_current_tenant())
              WITH CHECK (tenant_id = app_current_tenant());
            """
        )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_run_artifact_id_artifact"), "run", type_="foreignkey")
    op.drop_index(op.f("ix_run_artifact_id"), table_name="run")
    op.drop_column("run", "artifact_id")
    op.drop_table("process_record")
    op.drop_table("artifact_text")
    op.drop_table("artifact")
