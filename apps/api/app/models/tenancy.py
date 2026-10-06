"""회사 안의 구조: 조직 트리, 프로세스 체계, 역할 부여, 영역코드.

모든 테이블에 tenant_id 가 있고 행 수준 보안으로 격리한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk

ORG_UNIT_KINDS = ("company", "division", "team", "project")


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )


class OrgUnit(Base):
    __tablename__ = "org_unit"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at()


class ProcessSystem(Base):
    """프로세스 체계. parent_system_id 가 있으면 상위 체계를 상속하는 조직 변형이다."""

    __tablename__ = "process_system"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_unit.id", ondelete="RESTRICT"), nullable=False
    )
    parent_system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("process_system.id", ondelete="RESTRICT")
    )
    # 상속 계보의 최상위 체계. 문서 번호는 계보 전체에서 유일해야 하므로 여기에 묶어 발급한다.
    root_system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class RoleAssignment(Base):
    """체계 범위 역할. system_id 가 없으면 회사 전체에 적용된다."""

    __tablename__ = "role_assignment"
    __table_args__ = (
        Index(
            "uq_role_assignment_scope",
            "tenant_id",
            "user_id",
            "role",
            text("coalesce(system_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("process_system.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ScopeCode(Base):
    """영역코드(QMS, ISMS …). tenant_id 가 없으면 플랫폼 공통, 있으면 회사가 추가한 코드."""

    __tablename__ = "scope_code"
    __table_args__ = (
        Index(
            "uq_scope_code_tenant_code",
            text("coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "code",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    layer: Mapped[str | None] = mapped_column(String(32))
