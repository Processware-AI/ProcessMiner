"""표준·법규 원문과 거기서 도출한 요건, 그리고 오래 걸리는 작업(run)의 기록."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk
from .tenancy import tenant_fk


class SourceDocument(Base):
    """회사가 올린 원문 한 건. 원문 파일은 회사별 저장소에 두고 공유하지 않는다(저작권)."""

    __tablename__ = "source_document"
    __table_args__ = (UniqueConstraint("tenant_id", "sha256"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # 요건 번호 앞에 붙는 짧은 이름. 예: IEC62304
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    edition: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 글자가 거의 없어 문자 인식이 필요한 쪽 번호
    sparse_pages: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    # extracted → mining → mined → confirmed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="extracted")
    # 절(묶음)별 도출 결과: {"5.1": "done" | "failed"}
    mining_state: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourcePage(Base):
    __tablename__ = "source_page"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="CASCADE"), primary_key=True
    )
    page_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    text: Mapped[str] = mapped_column(Text, nullable=False)


class SourceClause(Base):
    __tablename__ = "source_clause"
    __table_args__ = (UniqueConstraint("source_id", "number"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)  # "5.1.1", "Annex B"
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # clause | annex
    normative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_number: Mapped[str | None] = mapped_column(String(32))
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 문서 안의 순서
    has_obligation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Requirement(Base):
    """원문에서 도출한 요건 하나. quote 는 원문 그대로이고, 조항에서 대조된 것만 확정할 수 있다."""

    __tablename__ = "requirement"
    __table_args__ = (UniqueConstraint("source_id", "code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clause_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_clause.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(48), nullable=False)  # "5.1.1-01"
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    obligation: Mapped[str] = mapped_column(String(8), nullable=False)  # shall | should | may
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    # 인용이 조항 본문에서 실제로 확인됐는가
    quote_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    applicability: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="proposed")
    # 도출한 모델. 사람이 직접 추가했으면 비운다.
    generated_by: Mapped[str | None] = mapped_column(String(64))
    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class Run(Base):
    """오래 걸리는 작업 한 건. 대기열이자 실행 기록이다."""

    __tablename__ = "run"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    # mine_requirements | design_system | write_documents
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued", index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_plan.id", ondelete="CASCADE"), index=True
    )
    # {"done": 3, "total": 31, "failed": 0, "input_tokens": …, "output_tokens": …}
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
