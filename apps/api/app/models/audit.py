import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditLog(Base):
    """추가 전용 감사 기록. 회사별로 앞 행의 해시를 이어 붙여 변조를 탐지한다.

    애플리케이션 역할에는 INSERT·SELECT 권한만 준다.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
