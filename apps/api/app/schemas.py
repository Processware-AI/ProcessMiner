import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

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
    # 산출물(회사의 기존 문서)을 AI 모델로 보내 처리하는 데 동의한다. 기본은 꺼짐이다.
    artifact_ai: bool | None = None


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    four_eyes: bool
    artifact_ai: bool
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
    open_revision_id: uuid.UUID | None
    # 초안에 남아 있는 〔조직 결정: …〕 항목 수. 0 이어야 검토를 요청할 수 있다.
    open_decisions: int
    updated_at: datetime
    # 테일러링: 보고 있는 체계에서 이 문서가 어떤 상태인가.
    # own(기준선 체계의 문서) | inherited(상위 문서를 그대로) | override(대체) | added | excluded
    tailoring: Literal["own", "inherited", "override", "added", "excluded"] = "own"
    tailoring_reason: str = ""
    tailoring_implied: bool = False  # 상위 문서가 제외돼 함께 제외됨
    home_system_slug: str = ""  # 문서가 속한 체계(상속이면 상위 체계)
    home_system_name: str = ""
    base_document_id: uuid.UUID | None = None  # 재정의가 대체한 상위 문서
    base_changed: bool = False  # 재정의한 뒤 상위 문서가 개정됨


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


class SystemRef(BaseModel):
    slug: str
    name: str


class RevisionRef(BaseModel):
    id: uuid.UUID
    version: str


class TailoringInfo(BaseModel):
    """보고 있는 체계에서 이 문서의 테일러링 상태와, 요청자가 할 수 있는 일."""

    state: Literal["own", "inherited", "override", "added", "excluded"]
    view_system: SystemRef  # 보고 있는 체계
    home_system: SystemRef  # 문서가 속한 체계
    reason: str
    implied: bool
    base: DocumentRef | None  # 재정의가 대체한 상위 문서
    base_system: SystemRef | None
    base_forked: RevisionRef | None  # 재정의가 기준으로 삼은 상위 판
    base_current: RevisionRef | None  # 상위 문서의 지금 승인판
    base_changed: bool
    actions: list[str]  # override | exclude | include | ack_base


class TailoringIn(BaseModel):
    reason: str = Field(default="", max_length=2000)


class DocumentDetail(BaseModel):
    document: DocumentSummary
    tailoring: TailoringInfo
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


class BatchReviewIn(BaseModel):
    """여러 개정판을 한 번에 검토 요청하거나 승인한다."""

    action: Literal["submit", "approve"]
    revision_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    comment: str = ""


class BatchItemResult(BaseModel):
    revision_id: uuid.UUID
    document: DocumentRef | None
    ok: bool
    error: str = ""


class BatchReviewOut(BaseModel):
    done: int
    failed: int
    results: list[BatchItemResult]


class DecisionOccurrence(BaseModel):
    revision_id: uuid.UUID
    document: DocumentRef
    section_key: str
    section_title: str
    before: str  # 같은 줄에서 항목 앞의 글
    after: str


class DecisionGroup(BaseModel):
    """같은 이름의 조직 결정 항목. 여러 문서에 걸쳐 있을 수 있다."""

    label: str
    occurrences: list[DecisionOccurrence]


class DecisionTarget(BaseModel):
    revision_id: uuid.UUID
    section_key: str


class DecisionFillIn(BaseModel):
    label: str = Field(max_length=500)
    value: str = Field(min_length=1, max_length=2000)
    # 채울 곳. 비우면 이 체계의 초안 전체에서 같은 이름의 항목을 모두 채운다.
    targets: list[DecisionTarget] | None = None


class DecisionFillOut(BaseModel):
    places: int
    documents: int


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
    # new: 새 문서 체계를 설계한다. extend: 이 체계의 기존 문서에 표준을 더한다.
    mode: Literal["new", "extend"] = "new"
    scope_code: str | None = Field(default=None, pattern=r"^[A-Z]{2,8}$")


_PlanTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_PlanText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class PlanInstructionIn(BaseModel):
    title: _PlanTitle
    purpose: _PlanText = ""
    requirements: list[str] = []
    integration_note: _PlanText = ""
    templates: list[_PlanTitle] = Field(default=[], max_length=3)


class PlanProcedureIn(BaseModel):
    title: _PlanTitle
    purpose: _PlanText = ""
    requirements: list[str] = []
    integration_note: _PlanText = ""
    instructions: list[PlanInstructionIn] = []


class PlanPolicyIn(BaseModel):
    title: _PlanTitle
    purpose: _PlanText = ""
    requirements: list[str] = []
    procedures: list[PlanProcedureIn] = []


class PlanEditIn(BaseModel):
    """사람이 고친 설계안 전체. 문서를 생성하기 전에만 바꿀 수 있다."""

    policies: list[PlanPolicyIn] = Field(min_length=1)


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
    # 기존 체계에 더하는 설계안: 개정할 기존 문서, 또는 새 문서를 붙일 기존 상위 문서
    target: DocumentRef | None = None
    anchor: DocumentRef | None = None
    status: str  # pending | done | failed
    document_id: uuid.UUID | None
    error: str


class PlanOut(BaseModel):
    id: uuid.UUID
    status: str  # designing | proposed | writing | partial | done | failed
    mode: str  # new | extend
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
    actions: list[str]  # write | edit | discard


class RevisionRequirementOut(BaseModel):
    section_key: str
    requirement: RequirementOut
    source: SourceRef


# ── 산출물과 기록 ────────────────────────────────────────────────────────────


class RecordTemplateOut(BaseModel):
    """기록을 만들 수 있는 양식."""

    document: DocumentRef
    instruction: str  # 상위 지침의 제목
    version: str
    approved: bool  # 승인된 양식인가. 아니면 작성 중인 판을 기준으로 한다.
    fields: list[str]


class MatchCandidateOut(BaseModel):
    document: DocumentRef
    confidence: int  # 0~100. 75 이상이면 바로 항목까지 뽑고, 50 미만이면 제안하지 않는다.
    reason: str


class RecordCounts(BaseModel):
    total: int
    empty: int  # 원본에 없어 비어 있는 항목(보완 대상)
    unverified: int  # 원본과 대조되지 않아 사람의 확인이 필요한 값
    human: int  # 사람이 채우거나 고친 항목


class RecordSummary(BaseModel):
    id: uuid.UUID
    code: str | None
    title: str
    status: str  # draft | published
    counts: RecordCounts


class ArtifactOut(BaseModel):
    id: uuid.UUID
    filename: str
    kind: str
    size_bytes: int
    char_count: int
    title: str
    performed_on: date | None
    # processing | needs_template | needs_confirm | review | published
    state: str
    match_state: str  # none | proposed | confirmed
    template: DocumentRef | None
    match_confidence: int | None
    candidates: list[MatchCandidateOut]
    record: RecordSummary | None
    run: RunOut | None
    created_at: datetime
    actions: list[str]  # match | set_template | delete


class SegmentOut(BaseModel):
    loc: str
    text: str


class ArtifactDetail(ArtifactOut):
    segments: list[SegmentOut]


class ArtifactTemplateIn(BaseModel):
    document_id: uuid.UUID


class RecordField(BaseModel):
    name: str
    value: str
    source: Literal["artifact", "human", "empty"]
    quote: str  # 값의 근거가 되는 원본 구절
    location: str  # 그 구절의 위치(쪽, 문단 …)
    verified: bool  # 구절이 실제로 원본에 있는지 코드가 확인했는가
    needs_check: bool  # 사람이 확인해야 발행할 수 있는 값인가
    original_value: str | None  # 사람이 고치기 전에 원본에서 옮겼던 값
    filled_by: UserRef | None
    filled_at: datetime | None
    confirmed_by: UserRef | None


class RecordOut(BaseModel):
    id: uuid.UUID
    code: str | None  # 발행할 때 발급한다
    title: str
    status: str
    legacy: bool
    performed_on: date | None
    template: DocumentRef
    template_version: str
    template_approved: bool
    artifact_id: uuid.UUID | None
    artifact_filename: str | None
    fields: list[RecordField]
    counts: RecordCounts
    generated_by: str | None
    created_at: datetime
    published_at: datetime | None
    published_by: UserRef | None
    actions: list[str]  # edit | publish


class RecordFieldIn(BaseModel):
    name: str
    value: str = Field(max_length=10_000)


class RecordPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    performed_on: date | None = None
    fields: list[RecordFieldIn] = []
    # 원본과 대조되지 않은 값을, 원본을 보고 맞다고 확인한 항목
    confirm: list[str] = []


# ── 표준 커버리지 ────────────────────────────────────────────────────────────


class CoverageDocument(BaseModel):
    """요건을 인용한 문서. 승인판과 진행 중인 판이 함께 있으면 승인판 기준이다."""

    id: uuid.UUID
    code: str
    title: str
    doc_type: str
    state: Literal["approved", "in_review", "draft"]
    sections: list[str]  # 인용한 섹션의 제목


class CoverageRecord(BaseModel):
    """요건을 이행한 증적: 발행한 기록."""

    id: uuid.UUID
    code: str
    title: str
    performed_on: date | None  # 수행일(없으면 발행일)
    legacy: bool  # 기존 산출물에서 옮긴 기록
    artifact_id: uuid.UUID | None


class CoverageRequirement(BaseModel):
    id: uuid.UUID
    code: str
    clause_number: str
    chapter: str  # 속한 장. "5" 또는 부속서의 "F"
    obligation: str
    summary: str
    # covered: 승인된 문서가 이행 | drafted: 승인 전 문서만 | gap: 문서 없음 | excluded: 적용 제외
    status: Literal["covered", "drafted", "gap", "excluded"]
    reason: str  # 제외 사유
    documents: list[CoverageDocument]
    records: list[CoverageRecord]  # 이 요건의 증적(기간을 주면 그 기간의 것)


class CoverageChapter(BaseModel):
    key: str
    title: str


class CoverageSource(BaseModel):
    source: SourceRef
    approved_at: datetime | None  # 적용요건을 승인한 때. 승인 전이면 요건이 바뀔 수 있다.
    total: int  # 확정된 요건 수
    excluded: int
    covered: int
    drafted: int
    gaps: int
    evidenced: int  # 기록(증적)이 하나 이상 있는 요건 수
    chapters: list[CoverageChapter]
    requirements: list[CoverageRequirement]


class CoverageOut(BaseModel):
    sources: list[CoverageSource]
    date_from: date | None
    date_to: date | None


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
