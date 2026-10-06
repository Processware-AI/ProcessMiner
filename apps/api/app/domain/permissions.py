"""권한 모델 — .claude/rbac/policy.yaml 의 6개 역할을 계승하고 범위를 추가한다.

세 층으로 판단한다.
  1. 플랫폼 역할: platform_admin 은 모든 회사에서 모든 행위가 가능하다.
  2. 회사 내 역할: tenant_admin 은 그 회사 안의 모든 행위가 가능하다.
     member 는 기본적으로 읽기만 가능하다.
  3. 체계 범위 역할: 회사 전체(system_id 없음) 또는 특정 체계에 부여한다.

사람은 이름이 아니라 사용자 id 로 식별한다.
"""

import uuid
from dataclasses import dataclass, field

PLATFORM_ADMIN = "platform_admin"
CONSULTANT = "consultant"

TENANT_ADMIN = "tenant_admin"
TENANT_MEMBER = "member"

SYSTEM_ROLES = ("process_owner", "executor", "auditor", "qmr", "admin", "viewer")

# 체계 범위 역할별 허용 행위
# basis.*: 체계의 근거(적용요건)를 고르고 승인한다. plan.manage: 요건에서 문서를 생성한다.
# doc.tailor: 상위 체계에서 물려받은 문서를 재정의하거나 제외한다.
_OWNER_ACTIONS = frozenset(
    {
        "doc.create",
        "doc.tailor",
        "doc.edit",
        "doc.submit",
        "doc.review",
        "basis.manage",
        "basis.approve",
        "plan.manage",
    }
)
_ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "admin": _OWNER_ACTIONS,
    "process_owner": _OWNER_ACTIONS,
    "qmr": frozenset({"doc.review", "basis.approve"}),
    "executor": frozenset(),
    "auditor": frozenset(),
    "viewer": frozenset(),
}

# 회사 구성원이면 누구나 가능한 행위
_MEMBER_ACTIONS = frozenset({"tenant.read", "system.read", "doc.read", "source.read"})

# tenant_admin 만 가능한 행위
_TENANT_ADMIN_ACTIONS = frozenset(
    {
        "tenant.manage",
        # 원문을 올리고, 요건을 도출·확정한다. 이후의 모든 문서가 이 요건을 근거로 삼는다.
        "source.manage",
        "tenant.archive",
        "tenant.restore",
        "system.create",
        "member.manage",
        "audit_log.read",
    }
)

# 플랫폼 관리자만 가능한 행위. 회사 관리자도 할 수 없다.
_PLATFORM_ADMIN_ACTIONS = frozenset({"tenant.delete"})

ALL_ACTIONS = (
    _MEMBER_ACTIONS
    | _TENANT_ADMIN_ACTIONS
    | _PLATFORM_ADMIN_ACTIONS
    | frozenset().union(*_ROLE_ACTIONS.values())
)

# 보관된 회사에서 할 수 있는 행위. 읽기와, 보관을 되돌리거나 끝내는 일뿐이다.
ARCHIVED_ACTIONS = frozenset(
    {
        "tenant.read",
        "system.read",
        "doc.read",
        "source.read",
        "audit_log.read",
        "tenant.restore",
        "tenant.delete",
    }
)


@dataclass(frozen=True)
class RoleGrant:
    role: str
    system_id: uuid.UUID | None  # None 이면 회사 전체


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    platform_role: str | None
    tenant_role: str | None  # 해당 회사의 구성원이 아니면 None
    grants: tuple[RoleGrant, ...] = field(default_factory=tuple)


def can(actor: Actor, action: str, system_id: uuid.UUID | None = None) -> bool:
    if action not in ALL_ACTIONS:
        raise ValueError(f"Unknown action: {action!r}")

    if actor.platform_role == PLATFORM_ADMIN:
        return True
    if actor.tenant_role is None or action in _PLATFORM_ADMIN_ACTIONS:
        return False
    if actor.tenant_role == TENANT_ADMIN:
        return True
    if action in _MEMBER_ACTIONS:
        return True
    if action in _TENANT_ADMIN_ACTIONS:
        return False

    return any(
        action in _ROLE_ACTIONS.get(g.role, frozenset())
        for g in actor.grants
        if g.system_id is None or g.system_id == system_id
    )


def can_create_tenant(platform_role: str | None) -> bool:
    return platform_role in (PLATFORM_ADMIN, CONSULTANT)


def violates_four_eyes(author_id: uuid.UUID, reviewer_id: uuid.UUID) -> bool:
    """작성자는 자기 개정판을 승인할 수 없다."""
    return author_id == reviewer_id
