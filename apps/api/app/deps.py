import uuid
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, set_tenant
from app.domain.permissions import (
    ALL_ACTIONS,
    ARCHIVED_ACTIONS,
    PLATFORM_ADMIN,
    TENANT_ADMIN,
    Actor,
    RoleGrant,
    can,
)
from app.errors import api_error, forbidden, not_found
from app.models import AppUser, Membership, ProcessSystem, RoleAssignment, Tenant
from app.services import auth as auth_service


def current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    token = request.cookies.get(get_settings().session_cookie)
    user = auth_service.user_for_session(db, token) if token else None
    if user is None:
        raise api_error(401, "unauthenticated", "로그인이 필요합니다.")
    return user


@dataclass
class TenantContext:
    """한 요청이 다루는 회사와, 그 회사 안에서의 요청자 권한."""

    db: Session
    user: AppUser
    tenant: Tenant
    actor: Actor

    @property
    def archived(self) -> bool:
        return self.tenant.archived_at is not None

    def can(self, action: str, system_id: uuid.UUID | None = None) -> bool:
        if not can(self.actor, action, system_id):
            return False
        # 보관된 회사는 읽기 전용이고, 보관·복원은 지금 상태에 맞는 쪽만 가능하다.
        if self.archived:
            return action in ARCHIVED_ACTIONS
        return action != "tenant.restore"

    def require(self, action: str, system_id: uuid.UUID | None = None) -> None:
        if not self.can(action, system_id):
            raise forbidden()

    def allowed_actions(self, system_id: uuid.UUID | None = None) -> list[str]:
        return sorted(a for a in ALL_ACTIONS if self.can(a, system_id))

    def system_by_slug(self, slug: str) -> ProcessSystem:
        system = self.db.scalar(select(ProcessSystem).where(ProcessSystem.slug == slug))
        if system is None:
            raise not_found("체계")
        return system


def tenant_context_any_state(
    tenant_slug: str,
    user: AppUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> TenantContext:
    """회사를 지정한다. 보관된 회사에도 쓸 수 있다(복원·삭제 요청용)."""
    tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    membership = (
        db.get(Membership, {"user_id": user.id, "tenant_id": tenant.id}) if tenant else None
    )
    # 소속이 없는 회사는 존재 여부도 드러내지 않는다.
    if tenant is None or (membership is None and user.platform_role != PLATFORM_ADMIN):
        raise not_found("회사")
    # 보관된 회사는 관리자에게만 보인다.
    is_admin = user.platform_role == PLATFORM_ADMIN or (
        membership is not None and membership.tenant_role == TENANT_ADMIN
    )
    if tenant.archived_at is not None and not is_admin:
        raise not_found("회사")

    # 이 시점부터 세션의 모든 쿼리는 이 회사 범위로 제한된다(행 수준 보안).
    set_tenant(db, tenant.id)

    grants = tuple(
        RoleGrant(role=r.role, system_id=r.system_id)
        for r in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == user.id))
    )
    actor = Actor(
        user_id=user.id,
        platform_role=user.platform_role,
        tenant_role=membership.tenant_role if membership else None,
        grants=grants,
    )
    return TenantContext(db=db, user=user, tenant=tenant, actor=actor)


def tenant_context(
    request: Request, ctx: TenantContext = Depends(tenant_context_any_state)
) -> TenantContext:
    """회사를 지정한다. 보관된 회사는 읽기 요청만 통과시킨다.

    권한 판단(TenantContext.can)도 보관 상태를 보지만, 권한 확인을 빠뜨린 처리 함수가
    있더라도 보관된 회사의 데이터가 바뀌지 않도록 여기서 한 번 더 막는다.
    """
    if ctx.archived and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise api_error(409, "tenant_archived", "보관된 회사는 바꿀 수 없습니다. 먼저 복원하세요.")
    return ctx
