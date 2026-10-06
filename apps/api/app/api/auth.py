from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import CommitRoute, get_db
from app.deps import current_user
from app.domain.permissions import PLATFORM_ADMIN, TENANT_ADMIN, can_create_tenant
from app.errors import api_error
from app.models import AppUser, Membership, Tenant
from app.schemas import LoginLinkIn, LoginLinkOut, MeOut, TenantSummary, UserOut, VerifyIn
from app.services import auth as auth_service

router = APIRouter(prefix="/api", tags=["auth"], route_class=CommitRoute)


@router.post("/auth/request-link", response_model=LoginLinkOut)
def request_link(payload: LoginLinkIn, db: Session = Depends(get_db)) -> LoginLinkOut:
    link = auth_service.create_login_link(db, payload.email)
    # 등록 여부를 드러내지 않도록 항상 같은 응답을 준다.
    # TODO(메일 발송): 운영 환경에서는 여기서 link 를 메일로 보낸다. 지금은 개발용 노출만 있다.
    return LoginLinkOut(dev_link=link if get_settings().auth_dev_echo else None)


@router.post("/auth/verify", response_model=UserOut)
def verify(payload: VerifyIn, response: Response, db: Session = Depends(get_db)) -> AppUser:
    user = auth_service.consume_login_token(db, payload.token)
    if user is None:
        raise api_error(400, "invalid_token", "로그인 링크가 만료됐거나 이미 사용됐습니다.")
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie,
        auth_service.create_session(db, user.id),
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie)
    if token:
        auth_service.delete_session(db, token)
    response.delete_cookie(settings.session_cookie, path="/")


@router.get("/me", response_model=MeOut)
def me(user: AppUser = Depends(current_user), db: Session = Depends(get_db)) -> MeOut:
    if user.platform_role == PLATFORM_ADMIN:
        rows = db.execute(
            select(Tenant, Membership.tenant_role)
            .outerjoin(
                Membership, (Membership.tenant_id == Tenant.id) & (Membership.user_id == user.id)
            )
            .order_by(Tenant.name)
        ).all()
    else:
        rows = db.execute(
            select(Tenant, Membership.tenant_role)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .where(Membership.user_id == user.id)
            .order_by(Tenant.name)
        ).all()
    is_platform_admin = user.platform_role == PLATFORM_ADMIN
    return MeOut(
        user=UserOut.model_validate(user),
        tenants=[
            TenantSummary(
                id=t.id, slug=t.slug, name=t.name, tenant_role=role, archived_at=t.archived_at
            )
            for t, role in rows
            # 보관된 회사는 관리자에게만 보인다.
            if t.archived_at is None or is_platform_admin or role == TENANT_ADMIN
        ],
        can_create_tenant=can_create_tenant(user.platform_role),
    )
