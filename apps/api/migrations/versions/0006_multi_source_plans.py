"""plans can integrate several source documents

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _qualify(structure: dict, uncovered: list, prefix: str) -> tuple[dict, list]:
    """설계안 안의 요건 코드 앞에 원문 약칭을 붙인다. "5.1.1-01" → "IEC62304 5.1.1-01"."""

    def fix(codes: list) -> list:
        return [f"{prefix} {code}" for code in codes]

    for policy in structure.get("policies", []):
        policy["requirements"] = fix(policy.get("requirements", []))
        for procedure in policy.get("procedures", []):
            procedure["requirements"] = fix(procedure.get("requirements", []))
            for instruction in procedure.get("instructions", []):
                instruction["requirements"] = fix(instruction.get("requirements", []))
    return structure, fix(uncovered)


def upgrade() -> None:
    op.create_table(
        "plan_source",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["generation_plan.id"],
            name=op.f("fk_plan_source_plan_id_generation_plan"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_document.id"],
            name=op.f("fk_plan_source_source_id_source_document"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_plan_source_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("plan_id", "source_id", name=op.f("pk_plan_source")),
    )
    op.create_index(op.f("ix_plan_source_tenant_id"), "plan_source", ["tenant_id"], unique=False)
    op.execute("ALTER TABLE plan_source ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON plan_source
          USING (tenant_id = app_current_tenant())
          WITH CHECK (tenant_id = app_current_tenant());
        """
    )

    # 기존 설계안은 원문 하나를 근거로 했다. 그 관계를 옮기고, 요건 코드에 원문 약칭을 붙인다
    # (여러 원문을 함께 다루면 "5.1.1-01" 같은 코드가 원문끼리 겹칠 수 있다).
    op.execute(
        "INSERT INTO plan_source (plan_id, source_id, tenant_id) "
        "SELECT id, source_id, tenant_id FROM generation_plan"
    )
    bind = op.get_bind()
    plans = bind.execute(
        sa.text(
            "SELECT p.id, p.structure, p.uncovered, s.code "
            "FROM generation_plan p JOIN source_document s ON s.id = p.source_id"
        )
    ).all()
    for plan_id, structure, uncovered, code in plans:
        structure, uncovered = _qualify(structure or {}, uncovered or [], code)
        bind.execute(
            sa.text(
                "UPDATE generation_plan SET structure = CAST(:structure AS jsonb), "
                "uncovered = CAST(:uncovered AS jsonb) WHERE id = :id"
            ),
            {
                "structure": json.dumps(structure, ensure_ascii=False),
                "uncovered": json.dumps(uncovered, ensure_ascii=False),
                "id": plan_id,
            },
        )

    op.drop_constraint(
        op.f("fk_generation_plan_source_id_source_document"), "generation_plan", type_="foreignkey"
    )
    op.drop_column("generation_plan", "source_id")


def downgrade() -> None:
    # 여러 원문을 묶은 설계안은 원문 하나짜리 구조로 되돌릴 수 없다.
    raise NotImplementedError("0006 은 되돌릴 수 없습니다. 백업에서 복원하세요.")
