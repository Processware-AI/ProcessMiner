"""프로세스 자산: 문서, 개정판, 문서 간 관계, 번호 발급 카운터."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk
from .tenancy import tenant_fk


class Document(Base):
    """문서의 정체성. 내용은 DocumentRevision 에 있다."""

    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("system_id", "code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("process_system.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    doc_type: Mapped[str] = mapped_column(
        String(8), ForeignKey("doc_type_def.code"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)  # 예: PRO-QMS-01-02
    scope_code: Mapped[str | None] = mapped_column(String(8))
    # 목록 표시용. 승인판이 있으면 승인판 제목, 없으면 초안 제목.
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="RESTRICT"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class DocumentRevision(Base):
    """문서의 한 개정판. 승인된 뒤에는 내용이 바뀌지 않는다(DB 트리거로 강제)."""

    __tablename__ = "document_revision"
    __table_args__ = (
        # 문서당 진행 중인 개정판은 하나, 승인판도 하나.
        Index(
            "uq_document_revision_open",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'in_review')"),
        ),
        Index(
            "uq_document_revision_approved",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(16), nullable=False)  # 승인되면 될 버전
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # [{key, title, body_md}] — 유형별 섹션 구성은 doc_type_def.sections 를 따른다.
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # RACI·KPI·단계·양식 필드 같은 구조화 데이터(이후 슬라이스에서 사용).
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    change_kind: Mapped[str] = mapped_column(String(8), nullable=False, default="major")
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    based_on_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_revision.id", ondelete="SET NULL")
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    # AI 가 작성한 경우 모델 id. 사람이 작성하면 비운다.
    generated_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class DocumentLink(Base):
    """상하위 외의 문서 간 관계(선후, 참조 등). 상하위는 Document.parent_id 로 표현한다."""

    __tablename__ = "document_link"
    __table_args__ = (UniqueConstraint("from_id", "to_id", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    from_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    to_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # follows | related
    created_at: Mapped[datetime] = created_at()


class DocSequence(Base):
    """문서 번호 카운터. 상속 계보(root_system_id) 단위로 유일한 번호를 발급한다."""

    __tablename__ = "doc_sequence"

    root_system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)  # 예: POL:QMS, WI:PRO-QMS-01-02
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    last: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
