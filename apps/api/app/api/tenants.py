"""회사, 조직 트리, 체계, 구성원, 영역코드, 감사 기록."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import storage
from app.db import CommitRoute, get_db, set_tenant
from app.deps import TenantContext, current_user, tenant_context, tenant_context_any_state
from app.domain.permissions import TENANT_ADMIN, can_create_tenant
from app.errors import api_error, forbidden, not_found
from app.models import (
    AppUser,
    AuditLog,
    Document,
    Membership,
    OrgUnit,
    ProcessSystem,
    RoleAssignment,
    ScopeCode,
    Tenant,
)
from app.schemas import (
    AuditEntryOut,
    AuditLogOut,
    MemberIn,
    MemberOut,
    MemberPatch,
    OrgUnitIn,
    OrgUnitOut,
    OrgUnitPatch,
    RoleGrantIO,
    ScopeCodeIn,
    ScopeCodeOut,
    SystemDetail,
    SystemIn,
    SystemOut,
    TenantIn,
    TenantOut,
    TenantPurgeIn,
    TenantPurgeOut,
    TenantSettingsIn,
    UserOut,
    UserRef,
)
from app.services import audit
from app.services.auth import normalize_email
from app.services.documents import four_eyes_enabled

router = APIRouter(prefix="/api", tags=["tenants"], route_class=CommitRoute)


def _tenant_out(ctx: TenantContext) -> TenantOut:
    return TenantOut(
        id=ctx.tenant.id,
        slug=ctx.tenant.slug,
        name=ctx.tenant.name,
        four_eyes=four_eyes_enabled(ctx.tenant),
        artifact_ai=bool(ctx.tenant.settings.get("artifact_ai", False)),
        tenant_role=ctx.actor.tenant_role,
        archived_at=ctx.tenant.archived_at,
        actions=ctx.allowed_actions(),
    )


# ── 회사 ─────────────────────────────────────────────────────────────────────


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(
    payload: TenantIn, user: AppUser = Depends(current_user), db: Session = Depends(get_db)
) -> TenantOut:
    if not can_create_tenant(user.platform_role):
        raise forbidden("회사를 만들 권한이 없습니다.")
    if db.scalar(select(Tenant.id).where(Tenant.slug == payload.slug)) is not None:
        raise api_error(409, "slug_taken", "이미 사용 중인 주소입니다.")

    tenant = Tenant(slug=payload.slug, name=payload.name, settings={"four_eyes": True})
    db.add(tenant)
    db.flush()
    db.add(Membership(user_id=user.id, tenant_id=tenant.id, tenant_role=TENANT_ADMIN))
    set_tenant(db, tenant.id)
    db.add(OrgUnit(tenant_id=tenant.id, kind="company", name=payload.name))
    db.flush()
    audit.record(
        db,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="tenant.create",
        entity_type="tenant",
        entity_id=tenant.id,
        data={"slug": tenant.slug, "name": tenant.name},
    )
    return _tenant_out(tenant_context_any_state(tenant.slug, user, db))


@router.get("/t/{tenant_slug}", response_model=TenantOut)
def get_tenant(ctx: TenantContext = Depends(tenant_context)) -> TenantOut:
    return _tenant_out(ctx)


@router.patch("/t/{tenant_slug}", response_model=TenantOut)
def update_tenant(
    payload: TenantSettingsIn, ctx: TenantContext = Depends(tenant_context)
) -> TenantOut:
    ctx.require("tenant.manage")
    changes = payload.model_dump(exclude_none=True)
    if "name" in changes:
        ctx.tenant.name = changes["name"]
    for key in ("four_eyes", "artifact_ai"):
        if key in changes:
            ctx.tenant.settings = {**ctx.tenant.settings, key: changes[key]}
    ctx.db.flush()
    if changes:
        audit.record(
            ctx.db,
            tenant_id=ctx.tenant.id,
            actor_id=ctx.user.id,
            action="tenant.update",
            entity_type="tenant",
            entity_id=ctx.tenant.id,
            data=changes,
        )
    return _tenant_out(ctx)


@router.post("/t/{tenant_slug}/archive", response_model=TenantOut)
def archive_tenant(ctx: TenantContext = Depends(tenant_context)) -> TenantOut:
    """회사를 보관한다. 데이터는 그대로 두고 읽기 전용으로 만들며, 일반 구성원에게는 숨긴다."""
    ctx.require("tenant.archive")
    ctx.tenant.archived_at = datetime.now(UTC)
    ctx.tenant.archived_by = ctx.user.id
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="tenant.archive",
        entity_type="tenant",
        entity_id=ctx.tenant.id,
        data={"slug": ctx.tenant.slug},
    )
    return _tenant_out(ctx)


@router.post("/t/{tenant_slug}/restore", response_model=TenantOut)
def restore_tenant(ctx: TenantContext = Depends(tenant_context_any_state)) -> TenantOut:
    ctx.require("tenant.restore")
    ctx.tenant.archived_at = None
    ctx.tenant.archived_by = None
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="tenant.restore",
        entity_type="tenant",
        entity_id=ctx.tenant.id,
        data={"slug": ctx.tenant.slug},
    )
    return _tenant_out(ctx)


@router.post("/t/{tenant_slug}/purge", response_model=TenantPurgeOut)
def purge_tenant(
    payload: TenantPurgeIn, ctx: TenantContext = Depends(tenant_context_any_state)
) -> TenantPurgeOut:
    """보관된 회사를 완전히 지운다. 문서·기록·감사 기록이 모두 사라지고 되돌릴 수 없다.

    지웠다는 사실(누가, 언제, 무엇을)은 deleted_tenant 에 남는다.
    """
    if not ctx.archived:
        raise api_error(409, "not_archived", "보관된 회사만 삭제할 수 있습니다. 먼저 보관하세요.")
    ctx.require("tenant.delete")
    if payload.confirm_slug != ctx.tenant.slug:
        raise api_error(422, "confirm_mismatch", "입력한 회사 주소가 일치하지 않습니다.")

    tenant_id, slug, name = ctx.tenant.id, ctx.tenant.slug, ctx.tenant.name
    summary = ctx.db.execute(
        text("SELECT purge_tenant(:tenant, :actor)"),
        {"tenant": ctx.tenant.id, "actor": ctx.user.id},
    ).scalar_one()
    # 세션이 들고 있던 이 회사의 객체는 이제 DB 에 없다.
    ctx.db.expunge_all()
    storage.delete_tenant(tenant_id)
    return TenantPurgeOut(slug=slug, name=name, summary=summary)


# ── 조직 트리 ────────────────────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/org-units", response_model=list[OrgUnitOut])
def list_org_units(ctx: TenantContext = Depends(tenant_context)) -> list[OrgUnit]:
    return list(ctx.db.scalars(select(OrgUnit).order_by(OrgUnit.sort, OrgUnit.created_at)))


@router.post("/t/{tenant_slug}/org-units", response_model=OrgUnitOut, status_code=201)
def create_org_unit(payload: OrgUnitIn, ctx: TenantContext = Depends(tenant_context)) -> OrgUnit:
    ctx.require("tenant.manage")
    if payload.parent_id is None:
        raise api_error(422, "parent_required", "상위 조직을 선택하세요.")
    if ctx.db.get(OrgUnit, payload.parent_id) is None:
        raise api_error(422, "parent_not_found", "상위 조직을 찾을 수 없습니다.")
    unit = OrgUnit(
        tenant_id=ctx.tenant.id, parent_id=payload.parent_id, kind=payload.kind, name=payload.name
    )
    ctx.db.add(unit)
    ctx.db.flush()
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="org_unit.create",
        entity_type="org_unit",
        entity_id=unit.id,
        data={"name": unit.name, "kind": unit.kind},
    )
    return unit


@router.patch("/t/{tenant_slug}/org-units/{unit_id}", response_model=OrgUnitOut)
def update_org_unit(
    unit_id: uuid.UUID, payload: OrgUnitPatch, ctx: TenantContext = Depends(tenant_context)
) -> OrgUnit:
    ctx.require("tenant.manage")
    unit = ctx.db.get(OrgUnit, unit_id)
    if unit is None:
        raise not_found("조직")
    if payload.name is not None:
        unit.name = payload.name
    if payload.kind is not None:
        if unit.parent_id is None and payload.kind != "company":
            raise api_error(422, "root_kind", "최상위 조직의 종류는 바꿀 수 없습니다.")
        unit.kind = payload.kind
    ctx.db.flush()
    return unit


@router.delete("/t/{tenant_slug}/org-units/{unit_id}", status_code=204)
def delete_org_unit(unit_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> None:
    ctx.require("tenant.manage")
    unit = ctx.db.get(OrgUnit, unit_id)
    if unit is None:
        raise not_found("조직")
    if unit.parent_id is None:
        raise api_error(409, "root_unit", "최상위 조직은 삭제할 수 없습니다.")
    if ctx.db.scalar(select(OrgUnit.id).where(OrgUnit.parent_id == unit.id).limit(1)):
        raise api_error(409, "has_children", "하위 조직이 있어 삭제할 수 없습니다.")
    if ctx.db.scalar(select(ProcessSystem.id).where(ProcessSystem.org_unit_id == unit.id).limit(1)):
        raise api_error(409, "has_systems", "이 조직에 속한 체계가 있어 삭제할 수 없습니다.")
    ctx.db.delete(unit)
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="org_unit.delete",
        entity_type="org_unit",
        entity_id=unit.id,
        data={"name": unit.name},
    )


# ── 체계 ─────────────────────────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/systems", response_model=list[SystemOut])
def list_systems(ctx: TenantContext = Depends(tenant_context)) -> list[ProcessSystem]:
    return list(ctx.db.scalars(select(ProcessSystem).order_by(ProcessSystem.created_at)))


@router.post("/t/{tenant_slug}/systems", response_model=SystemOut, status_code=201)
def create_system(payload: SystemIn, ctx: TenantContext = Depends(tenant_context)) -> ProcessSystem:
    ctx.require("system.create")
    db = ctx.db
    if db.get(OrgUnit, payload.org_unit_id) is None:
        raise api_error(422, "org_unit_not_found", "조직을 찾을 수 없습니다.")
    if db.scalar(select(ProcessSystem.id).where(ProcessSystem.slug == payload.slug)) is not None:
        raise api_error(409, "slug_taken", "이 회사에서 이미 사용 중인 주소입니다.")

    system_id = uuid.uuid4()
    root_system_id = system_id
    if payload.parent_system_id is not None:
        parent = db.get(ProcessSystem, payload.parent_system_id)
        if parent is None:
            raise api_error(422, "parent_not_found", "상위 체계를 찾을 수 없습니다.")
        root_system_id = parent.root_system_id

    system = ProcessSystem(
        id=system_id,
        tenant_id=ctx.tenant.id,
        org_unit_id=payload.org_unit_id,
        parent_system_id=payload.parent_system_id,
        root_system_id=root_system_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        created_by=ctx.user.id,
    )
    db.add(system)
    db.flush()
    audit.record(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="system.create",
        entity_type="system",
        entity_id=system.id,
        data={"slug": system.slug, "name": system.name},
    )
    return system


@router.get("/t/{tenant_slug}/systems/{system_slug}", response_model=SystemDetail)
def get_system(system_slug: str, ctx: TenantContext = Depends(tenant_context)) -> SystemDetail:
    system = ctx.system_by_slug(system_slug)
    count = ctx.db.scalar(
        select(func.count()).select_from(Document).where(Document.system_id == system.id)
    )
    return SystemDetail(
        **SystemOut.model_validate(system).model_dump(),
        document_count=count or 0,
        actions=ctx.allowed_actions(system.id),
    )


# ── 구성원 ───────────────────────────────────────────────────────────────────


def _member_out(db: Session, user: AppUser, tenant_role: str) -> MemberOut:
    grants = db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == user.id))
    return MemberOut(
        user=UserOut.model_validate(user),
        tenant_role=tenant_role,
        roles=[RoleGrantIO(role=g.role, system_id=g.system_id) for g in grants],
    )


def _replace_roles(ctx: TenantContext, user_id: uuid.UUID, roles: list[RoleGrantIO]) -> None:
    db = ctx.db
    for existing in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == user_id)):
        db.delete(existing)
    db.flush()
    for grant in {(g.role, g.system_id) for g in roles}:
        role, system_id = grant
        if system_id is not None and db.get(ProcessSystem, system_id) is None:
            raise api_error(422, "system_not_found", "역할을 부여할 체계를 찾을 수 없습니다.")
        db.add(
            RoleAssignment(tenant_id=ctx.tenant.id, user_id=user_id, system_id=system_id, role=role)
        )
    db.flush()


@router.get("/t/{tenant_slug}/members", response_model=list[MemberOut])
def list_members(ctx: TenantContext = Depends(tenant_context)) -> list[MemberOut]:
    rows = ctx.db.execute(
        select(AppUser, Membership.tenant_role)
        .join(Membership, Membership.user_id == AppUser.id)
        .where(Membership.tenant_id == ctx.tenant.id)
        .order_by(AppUser.name)
    ).all()
    return [_member_out(ctx.db, user, role) for user, role in rows]


@router.post("/t/{tenant_slug}/members", response_model=MemberOut, status_code=201)
def add_member(payload: MemberIn, ctx: TenantContext = Depends(tenant_context)) -> MemberOut:
    ctx.require("member.manage")
    db = ctx.db
    email = normalize_email(payload.email)
    user = db.scalar(select(AppUser).where(AppUser.email == email))
    if user is None:
        user = AppUser(email=email, name=payload.name)
        db.add(user)
        db.flush()
    if db.get(Membership, {"user_id": user.id, "tenant_id": ctx.tenant.id}) is not None:
        raise api_error(409, "already_member", "이미 이 회사의 구성원입니다.")
    db.add(Membership(user_id=user.id, tenant_id=ctx.tenant.id, tenant_role=payload.tenant_role))
    db.flush()
    _replace_roles(ctx, user.id, payload.roles)
    audit.record(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="member.add",
        entity_type="user",
        entity_id=user.id,
        data={
            "email": email,
            "tenant_role": payload.tenant_role,
            "roles": [r.model_dump(mode="json") for r in payload.roles],
        },
    )
    return _member_out(db, user, payload.tenant_role)


@router.patch("/t/{tenant_slug}/members/{user_id}", response_model=MemberOut)
def update_member(
    user_id: uuid.UUID, payload: MemberPatch, ctx: TenantContext = Depends(tenant_context)
) -> MemberOut:
    ctx.require("member.manage")
    db = ctx.db
    membership = db.get(Membership, {"user_id": user_id, "tenant_id": ctx.tenant.id})
    user = db.get(AppUser, user_id)
    if membership is None or user is None:
        raise not_found("구성원")

    if payload.tenant_role is not None and payload.tenant_role != membership.tenant_role:
        if membership.tenant_role == TENANT_ADMIN:
            admins = db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.tenant_id == ctx.tenant.id, Membership.tenant_role == TENANT_ADMIN
                )
            )
            if admins == 1:
                raise api_error(409, "last_admin", "마지막 관리자의 권한은 내릴 수 없습니다.")
        membership.tenant_role = payload.tenant_role
    if payload.roles is not None:
        _replace_roles(ctx, user_id, payload.roles)
    db.flush()
    audit.record(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="member.update",
        entity_type="user",
        entity_id=user_id,
        data=payload.model_dump(mode="json", exclude_none=True),
    )
    return _member_out(db, user, membership.tenant_role)


# ── 영역코드 ─────────────────────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/scope-codes", response_model=list[ScopeCodeOut])
def list_scope_codes(ctx: TenantContext = Depends(tenant_context)) -> list[ScopeCodeOut]:
    rows = ctx.db.scalars(select(ScopeCode).order_by(ScopeCode.code))
    return [
        ScopeCodeOut(code=r.code, name=r.name, layer=r.layer, custom=r.tenant_id is not None)
        for r in rows
    ]


@router.post("/t/{tenant_slug}/scope-codes", response_model=ScopeCodeOut, status_code=201)
def create_scope_code(
    payload: ScopeCodeIn, ctx: TenantContext = Depends(tenant_context)
) -> ScopeCodeOut:
    ctx.require("tenant.manage")
    if ctx.db.scalar(select(ScopeCode.id).where(ScopeCode.code == payload.code)) is not None:
        raise api_error(409, "code_taken", "이미 있는 영역코드입니다.")
    row = ScopeCode(tenant_id=ctx.tenant.id, code=payload.code, name=payload.name)
    ctx.db.add(row)
    ctx.db.flush()
    return ScopeCodeOut(code=row.code, name=row.name, layer=row.layer, custom=True)


# ── 감사 기록 ────────────────────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/audit-log", response_model=AuditLogOut)
def get_audit_log(
    limit: int = Query(default=100, ge=1, le=500), ctx: TenantContext = Depends(tenant_context)
) -> AuditLogOut:
    ctx.require("audit_log.read")
    rows = ctx.db.execute(
        select(AuditLog, AppUser)
        .outerjoin(AppUser, AppUser.id == AuditLog.actor_id)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    ).all()
    broken_at = audit.verify_chain(ctx.db, ctx.tenant.id)
    return AuditLogOut(
        entries=[
            AuditEntryOut(
                id=entry.id,
                at=entry.at,
                actor=UserRef(id=user.id, name=user.name) if user else None,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                data=entry.data,
            )
            for entry, user in rows
        ],
        chain_intact=broken_at is None,
        broken_at=broken_at,
    )
