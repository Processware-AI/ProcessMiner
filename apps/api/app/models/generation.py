"""체계의 근거(적용요건)와 문서 생성 계획, 그리고 문서 ↔ 요건 근거 링크."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk
from .tenancy import tenant_fk


class SystemBasis(Base):
    """체계가 근거로 삼는 원문. 승인되면 그 원문의 적용요건이 이 체계의 기준선이 된다."""

    __tablename__ = "system_basis"

    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("process_system.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="RESTRICT"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequirementExclusion(Base):
    """이 체계에는 적용하지 않기로 한 요건. 사유가 있어야 한다(심사에서 설명해야 하므로)."""

    __tablename__ = "requirement_exclusion"

    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("process_system.id", ondelete="CASCADE"), primary_key=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    excluded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class GenerationPlan(Base):
    """문서 구조 설계안. 사람이 받아들인 뒤에야 문서를 쓴다."""

    __tablename__ = "generation_plan"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("process_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_code: Mapped[str] = mapped_column(String(8), nullable=False)
    # new: 새 문서 체계를 설계한다.
    # extend: 이미 있는 문서 체계에 표준을 더한다(기존 문서 개정 + 필요한 새 문서).
    mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="new", server_default="new"
    )
    # designing → proposed → writing → done | failed | discarded
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="designing")
    # {"policies": [{title, purpose, requirements[],
    #                procedures: [{…, instructions: [{…, templates[]}]}]}]}
    structure: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 어느 문서에도 배정되지 않은 적용요건 코드. 비어 있어야 받아들일 수 있다.
    uncovered: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # 문서별 생성 결과: {"path": {"status": "done"|"failed", "document_id": …, "error": …}}
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    model: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanSource(Base):
    """설계안이 근거로 삼는 원문. 여러 표준을 한 설계안에서 통합할 수 있다."""

    __tablename__ = "plan_source"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_plan.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="RESTRICT"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = tenant_fk()


class DocumentRequirement(Base):
    """문서의 어느 섹션이 어느 요건을 근거로 하는지. 커버리지와 심사 증적 묶음의 바탕이다."""

    __tablename__ = "document_requirement"

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_revision.id", ondelete="CASCADE"),
        primary_key=True,
    )
    section_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement.id", ondelete="RESTRICT"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
