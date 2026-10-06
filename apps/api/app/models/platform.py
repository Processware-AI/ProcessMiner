"""회사 경계 밖의 테이블: 사용자, 로그인, 회사, 소속, 참조 데이터.

여기 있는 테이블에는 행 수준 보안이 없다. 인증·회사 선택 코드만 접근한다.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, uuid_pk


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)  # 소문자 저장
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    platform_role: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at()


class LoginToken(Base):
    """일회용 로그인 링크. 토큰 원문은 저장하지 않는다."""

    __tablename__ = "login_token"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at()


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at()
    # 보관된 회사는 읽기 전용이다. 완전 삭제는 보관된 회사에만 할 수 있다.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )


class DeletedTenant(Base):
    """완전 삭제된 회사의 흔적. 회사의 감사 기록도 함께 지워지므로 누가 언제 지웠는지 여기 남긴다.

    애플리케이션 역할에는 SELECT 권한만 준다. 행은 purge_tenant() 함수만 쓴다.
    """

    __tablename__ = "deleted_tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    deleted_at: Mapped[datetime] = created_at()
    # 삭제한 사람의 계정이 나중에 없어져도 알아볼 수 있게 이메일을 함께 남긴다.
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deleted_by_email: Mapped[str] = mapped_column(String(320), nullable=False)
    # 지워진 행 수와 감사 기록의 마지막 지문
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Membership(Base):
    __tablename__ = "membership"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()


class DocTypeDef(Base):
    """문서 유형 정의(참조 데이터). seed/doc_types.yaml 에서 적재한다."""

    __tablename__ = "doc_type_def"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parent_type: Mapped[str | None] = mapped_column(String(8))
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{key, title, hint, required, template}]
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class StandardDef(Base):
    """표준 분류 레지스트리(참조 데이터). seed/standards.yaml 에서 적재한다."""

    __tablename__ = "standard_def"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    structure: Mapped[str] = mapped_column(String(32), nullable=False)
    integration_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
