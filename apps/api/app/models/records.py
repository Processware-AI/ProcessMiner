"""기존 산출물과, 그것을 표준 양식에 맞춰 옮긴 기록."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk
from .tenancy import tenant_fk


class Artifact(Base):
    """조직이 이미 갖고 있던 산출물 파일 한 건. 원본 파일은 바꾸지 않고 보관한다."""

    __tablename__ = "artifact"
    __table_args__ = (UniqueConstraint("system_id", "sha256"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("process_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # pdf | docx | xlsx | …
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # 원본의 업무를 수행한 날. 원본에 적혀 있을 때만 채운다(정규화한 날과 다르다).
    performed_on: Mapped[date | None] = mapped_column(Date)

    # 어느 양식의 기록인가. none → proposed(모델 제안) → confirmed(사람이 확정)
    match_state: Mapped[str] = mapped_column(String(12), nullable=False, default="none")
    template_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )
    match_confidence: Mapped[int | None] = mapped_column(Integer)
    # [{document_id, code, title, confidence, reason}] 일치도가 높은 순
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class ArtifactText(Base):
    """산출물에서 뽑은 글자. 위치가 붙은 조각의 목록이다. 목록 조회에 딸려 오지 않게 따로 둔다."""

    __tablename__ = "artifact_text"

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artifact.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    # [{loc, text}]
    segments: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)


class ProcessRecord(Base):
    """표준 양식에 맞춘 기록 한 건. 어느 양식의 어느 판으로 만들었는지를 고정한다."""

    __tablename__ = "process_record"
    __table_args__ = (
        UniqueConstraint("system_id", "code"),
        Index(
            "uq_process_record_artifact",
            "artifact_id",
            unique=True,
            postgresql_where=text("artifact_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("process_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 발행할 때 발급한다. 예: REC-QMS-01-01-01-01-003
    code: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    template_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="RESTRICT"), nullable=False
    )
    template_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_revision.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artifact.id", ondelete="SET NULL")
    )
    # [{name, value, source, quote, location, verified, filled_by, filled_at}]
    #   source: artifact(원본에서 옮김) | human(사람이 채우거나 고침) | empty(비어 있음)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    performed_on: Mapped[date | None] = mapped_column(Date)
    # 표준 양식이 생기기 전의 산출물에서 옮긴 기록인가
    legacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    generated_by: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
