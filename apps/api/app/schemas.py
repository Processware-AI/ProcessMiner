import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# 웹 주소의 첫 구간이 회사 주소이므로, 화면 경로와 겹치는 이름은 쓸 수 없다.
RESERVED_TENANT_SLUGS = {"api", "auth", "login", "logout", "new", "admin", "static", "public"}


def _check_slug(value: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise ValueError("영문 소문자·숫자·하이픈 2~63자로 입력하세요.")
    return value


def _check_tenant_slug(value: str) -> str:
    if _check_slug(value) in RESERVED_TENANT_SLUGS:
        raise ValueError("사용할 수 없는 주소입니다.")
    return value


# ── 인증 ─────────────────────────────────────────────────────────────────────


class LoginLinkIn(BaseModel):
    email: EmailStr


class LoginLinkOut(BaseModel):
    sent: bool = True
    dev_link: str | None = None  # 개발 설정에서만 채워진다


class VerifyIn(BaseModel):
    token: str


class UserOut(Out):
    id: uuid.UUID
    email: str
    name: str
    platform_role: str | None


class UserRef(Out):
    id: uuid.UUID
    name: str


class TenantSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    tenant_role: str | None
    archived_at: datetime | None


class MeOut(BaseModel):
    user: UserOut
    tenants: list[TenantSummary]
    can_create_tenant: bool


# ── 회사·조직·체계 ───────────────────────────────────────────────────────────


class TenantIn(BaseModel):
    slug: str
    name: str = Field(min_length=1, max_length=200)

    _slug = field_validator("slug")(_check_tenant_slug)


class TenantSettingsIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    four_eyes: bool | None = None


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    four_eyes: bool
    tenant_role: str | None
    archived_at: datetime | None
    actions: list[str]


class TenantPurgeIn(BaseModel):
    confirm_slug: str  # 실수로 지우지 않도록 회사 주소를 직접 입력받는다


class TenantPurgeOut(BaseModel):
    slug: str
    name: str
    summary: dict[str, Any]  # 지워진 행 수


OrgUnitKind = Literal["company", "division", "team", "project"]


class OrgUnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: OrgUnitKind
    parent_id: uuid.UUID | None = None


class OrgUnitPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: OrgUnitKind | None = None


class OrgUnitOut(Out):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    kind: str
    name: str
    sort: int


class SystemIn(BaseModel):
    slug: str
    name: str = Field(min_length=1, max_length=200)
    org_unit_id: uuid.UUID
    parent_system_id: uuid.UUID | None = None
    description: str = ""

    _slug = field_validator("slug")(_check_slug)


class SystemOut(Out):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    org_unit_id: uuid.UUID
    parent_system_id: uuid.UUID | None
    root_system_id: uuid.UUID
    created_at: datetime


class SystemDetail(SystemOut):
    document_count: int
    actions: list[str]


# ── 구성원 ───────────────────────────────────────────────────────────────────

TenantRole = Literal["tenant_admin", "member"]
SystemRole = Literal["process_owner", "executor", "auditor", "qmr", "admin", "viewer"]


class RoleGrantIO(BaseModel):
    role: SystemRole
    system_id: uuid.UUID | None = None


class MemberIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    tenant_role: TenantRole = "member"
    roles: list[RoleGrantIO] = []


class MemberPatch(BaseModel):
    tenant_role: TenantRole | None = None
    roles: list[RoleGrantIO] | None = None


class MemberOut(BaseModel):
    user: UserOut
    tenant_role: str
    roles: list[RoleGrantIO]


# ── 참조 데이터 ──────────────────────────────────────────────────────────────


class SectionSpec(BaseModel):
    key: str
    title: str
    required: bool = False
    hint: str = ""
    template: str = ""
    normative: bool = False  # 근거 요건이 반드시 있어야 하는 섹션


class DocTypeOut(BaseModel):
    code: str
    name: str
    description: str
    parent_type: str | None
    sections: list[SectionSpec]


class ScopeCodeIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{2,8}$")
    name: str = Field(min_length=1, max_length=100)


class ScopeCodeOut(Out):
    code: str
    name: str
    layer: str | None
    custom: bool


# ── 문서 ─────────────────────────────────────────────────────────────────────


class Section(BaseModel):
    key: str
    title: str
    body_md: str = ""


class RevisionMeta(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version: str
    status: str
    title: str
    change_kind: str
    change_summary: str
    author: UserRef | None
    reviewer: UserRef | None
    review_comment: str
    submitted_at: datetime | None
    reviewed_at: datetime | None
    approved_at: datetime | None
    content_hash: str | None
    generated_by: str | None
    created_at: datetime
    updated_at: datetime


class RevisionOut(RevisionMeta):
    sections: list[Section]
    structured: dict[str, Any]


class DocumentSummary(BaseModel):
    id: uuid.UUID
    system_id: uuid.UUID
    doc_type: str
    code: str
    scope_code: str | None
    title: str
    parent_id: uuid.UUID | None
    approved_version: str | None
    approved_at: datetime | None
    open_status: str | None  # 진행 중인 개정판의 상태
    open_version: str | None
    updated_at: datetime


class DocumentIn(BaseModel):
    doc_type: str
    title: str = Field(min_length=1, max_length=300)
    scope_code: str | None = None
    parent_id: uuid.UUID | None = None


class DocumentRef(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    doc_type: str


class DocumentDetail(BaseModel):
    document: DocumentSummary
    system: SystemOut
    ancestors: list[DocumentRef]  # 최상위부터 바로 위 문서까지
    children: list[DocumentSummary]
    approved: RevisionOut | None
    open: RevisionOut | None
    actions: list[str]  # 요청자가 이 문서에 할 수 있는 행위


class RevisionStartIn(BaseModel):
    change_kind: Literal["minor", "major"] = "minor"
    change_summary: str = ""


class RevisionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    sections: list[Section] | None = None
    change_kind: Literal["minor", "major"] | None = None
    change_summary: str | None = None


class ReviewIn(BaseModel):
    comment: str = ""


class InboxItem(BaseModel):
    kind: Literal["to_review", "my_draft", "returned", "my_in_review"]
    document: DocumentRef
    system_slug: str
    system_name: str
    revision: RevisionMeta


# ── 원문과 요건 ──────────────────────────────────────────────────────────────


class RunOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str  # queued | running | succeeded | failed
    progress: dict[str, Any]
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[str]  # 최근 진행 기록


class RequirementCounts(BaseModel):
    proposed: int
    confirmed: int
    rejected: int
    unverified: int  # 원문에서 인용이 확인되지 않은 요건(제외한 것은 세지 않는다)


class SourceOut(BaseModel):
    id: uuid.UUID
    title: str
    code: str
    edition: str
    filename: str
    size_bytes: int
    page_count: int
    sparse_pages: list[int]
    status: str  # extracted | mining | mined | confirmed
    clause_count: int
    obligation_clause_count: int  # 의무 표현이 있어 요건 도출 대상인 조항 수
    requirements: RequirementCounts
    failed_units: list[str]  # 요건 도출에 실패한 절
    uploaded_by: UserRef | None
    created_at: datetime
    confirmed_by: UserRef | None
    confirmed_at: datetime | None
    run: RunOut | None  # 가장 최근 작업
    actions: list[str]


class ClauseSummary(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    kind: str
    normative: bool
    level: int
    parent_number: str | None
    page_start: int
    page_end: int
    has_obligation: bool
    requirement_count: int
    unverified_count: int


class RequirementOut(BaseModel):
    id: uuid.UUID
    clause_id: uuid.UUID
    clause_number: str
    code: str
    obligation: str
    category: str
    summary: str
    quote: str
    quote_verified: bool
    page_no: int | None
    applicability: str
    evidence: list[str]
    status: str  # proposed | confirmed | rejected
    generated_by: str | None


class ClauseDetail(ClauseSummary):
    text: str
    requirements: list[RequirementOut]


class RequirementPatch(BaseModel):
    summary: str | None = Field(default=None, min_length=1)
    evidence: list[str] | None = None
    status: Literal["proposed", "rejected"] | None = None


# ── 체계의 근거와 문서 생성 ──────────────────────────────────────────────────


class SourceRef(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    edition: str


class BasisItem(BaseModel):
    source: SourceRef
    total: int  # 확정된 요건 수
    excluded: int  # 이 체계에 적용하지 않기로 한 요건 수
    approved_at: datetime | None
    approved_by: UserRef | None
    actions: list[str]  # review | approve | reopen | detach | design


class BasisOut(BaseModel):
    items: list[BasisItem]
    available: list[SourceRef]  # 근거로 추가할 수 있는(요건을 확정한) 원문
    actions: list[str]  # attach


class BasisAttachIn(BaseModel):
    source_id: uuid.UUID


class BasisRequirementOut(RequirementOut):
    excluded: bool
    reason: str


class ExclusionIn(BaseModel):
    excluded: bool
    reason: str = ""


class PlanStartIn(BaseModel):
    # 함께 설계할 근거 원문. 여럿이면 하나의 문서 체계로 통합한다.
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    scope_code: str = Field(pattern=r"^[A-Z]{2,8}$")


class PlanWriteIn(BaseModel):
    # 문서를 생성할 정책의 경로(p0, p1 …). 비우면 남은 문서를 모두 생성한다.
    policies: list[str] | None = None


class PlanNodeOut(BaseModel):
    path: str
    doc_type: str
    title: str
    purpose: str
    parent: str | None
    requirements: list[str]  # 배정된 요건 코드. "원문약칭 번호" 모양
    # 배정된 요건을 표준별로 나눈 것: {"IEC62304": ["5.1.1-01", …]}
    by_standard: dict[str, list[str]]
    integration_note: str  # 여러 표준의 요건이 이 문서에서 어떻게 맞물리는지
    status: str  # pending | done | failed
    document_id: uuid.UUID | None
    error: str


class PlanOut(BaseModel):
    id: uuid.UUID
    status: str  # designing | proposed | writing | partial | done | failed
    scope_code: str
    sources: list[SourceRef]
    model: str | None
    applicable_count: int
    applicable_by_standard: dict[str, int]
    uncovered: list[str]
    nodes: list[PlanNodeOut]
    created_at: datetime
    accepted_at: datetime | None
    run: RunOut | None
    actions: list[str]  # write | discard


class RevisionRequirementOut(BaseModel):
    section_key: str
    requirement: RequirementOut
    source: SourceRef


# ── 감사 기록 ────────────────────────────────────────────────────────────────


class AuditEntryOut(BaseModel):
    id: int
    at: datetime
    actor: UserRef | None
    action: str
    entity_type: str
    entity_id: str
    data: dict[str, Any]


class AuditLogOut(BaseModel):
    entries: list[AuditEntryOut]
    chain_intact: bool
    broken_at: int | None
