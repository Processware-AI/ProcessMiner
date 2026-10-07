"""문서와 개정판의 업무 규칙.

호출 전에 세션에 회사가 지정돼 있어야 한다(행 수준 보안). 권한 확인은 라우터가 한다.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.domain import revisions as rev
from app.domain.doc_types import DOC_TYPES, PARENT_TYPE, SCOPED_ROOT_TYPES
from app.domain.permissions import violates_four_eyes
from app.errors import api_error, not_found
from app.models import (
    AppUser,
    DocTypeDef,
    Document,
    DocumentRequirement,
    DocumentRevision,
    ProcessSystem,
    ScopeCode,
    Tenant,
)
from app.schemas import (
    DocumentIn,
    DocumentRef,
    DocumentSummary,
    RevisionMeta,
    RevisionOut,
    RevisionPatch,
    Section,
    UserRef,
)
from app.services import audit, tailoring
from app.services.numbering import allocate_code

# ── 조회 ─────────────────────────────────────────────────────────────────────


def _summaries(db: Session, *conditions) -> list[DocumentSummary]:
    approved = aliased(DocumentRevision)
    opened = aliased(DocumentRevision)
    rows = db.execute(
        select(Document, approved, opened)
        .outerjoin(
            approved, (approved.document_id == Document.id) & (approved.status == rev.APPROVED)
        )
        .outerjoin(
            opened,
            (opened.document_id == Document.id) & (opened.status.in_(rev.OPEN_STATUSES)),
        )
        .where(*conditions)
        .order_by(Document.code)
    ).all()
    return [_summary(doc, a, o) for doc, a, o in rows]


def _summary(
    doc: Document, approved: DocumentRevision | None, opened: DocumentRevision | None
) -> DocumentSummary:
    latest = max(
        (r.updated_at for r in (approved, opened) if r is not None), default=doc.created_at
    )
    return DocumentSummary(
        id=doc.id,
        system_id=doc.system_id,
        doc_type=doc.doc_type,
        code=doc.code,
        scope_code=doc.scope_code,
        title=doc.title,
        parent_id=doc.parent_id,
        approved_version=approved.version if approved else None,
        approved_at=approved.approved_at if approved else None,
        open_status=opened.status if opened else None,
        open_version=opened.version if opened else None,
        open_revision_id=opened.id if opened else None,
        open_decisions=(
            len(rev.open_decisions(opened.sections)) if opened and opened.status == rev.DRAFT else 0
        ),
        updated_at=latest,
    )


def effective_summaries(db: Session, entries: list[tailoring.Effective]) -> list[DocumentSummary]:
    """실효 문서(tailoring.effective_documents 의 결과)를 목록에 보여줄 모양으로 만든다."""
    if not entries:
        return []
    rows = {s.id: s for s in _summaries(db, Document.id.in_([e.doc.id for e in entries]))}
    # 재정의한 문서: 그 뒤로 상위 문서가 개정됐는지 본다.
    bases = [e.base.id for e in entries if e.base is not None]
    current_base = (
        dict(
            db.execute(
                select(DocumentRevision.document_id, DocumentRevision.id).where(
                    DocumentRevision.document_id.in_(bases),
                    DocumentRevision.status == rev.APPROVED,
                )
            ).all()
        )
        if bases
        else {}
    )
    result = []
    for entry in entries:
        update: dict[str, Any] = {
            "parent_id": entry.parent_id,
            "tailoring": entry.state,
            "tailoring_reason": entry.reason,
            "tailoring_implied": entry.implied,
            "home_system_slug": entry.home.slug,
            "home_system_name": entry.home.name,
        }
        if entry.base is not None:
            current = current_base.get(entry.base.id)
            update["base_document_id"] = entry.base.id
            update["base_changed"] = current is not None and current != entry.doc.base_revision_id
        if entry.state in ("inherited", "excluded"):
            # 상위 체계에서 진행 중인 개정은 이 체계의 일이 아니다. 승인판만 내려온다.
            update |= {
                "open_status": None,
                "open_version": None,
                "open_revision_id": None,
                "open_decisions": 0,
            }
        result.append(rows[entry.doc.id].model_copy(update=update))
    return result


def list_documents(db: Session, system: ProcessSystem) -> list[DocumentSummary]:
    """이 체계에서 쓰이는 문서: 자기 문서와, 상위 체계에서 물려받은 문서."""
    return effective_summaries(db, tailoring.effective_documents(db, system))


def list_children(db: Session, document_id: uuid.UUID) -> list[DocumentSummary]:
    return _summaries(db, Document.parent_id == document_id)


def get_summary(db: Session, document_id: uuid.UUID) -> DocumentSummary:
    found = _summaries(db, Document.id == document_id)
    if not found:
        raise not_found("문서")
    return found[0]


def get_document(db: Session, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise not_found("문서")
    return doc


def get_revision(db: Session, revision_id: uuid.UUID) -> DocumentRevision:
    revision = db.get(DocumentRevision, revision_id)
    if revision is None:
        raise not_found("개정판")
    return revision


def ancestors(db: Session, doc: Document) -> list[DocumentRef]:
    chain: list[DocumentRef] = []
    parent_id = doc.parent_id
    while parent_id is not None:
        parent = db.get(Document, parent_id)
        if parent is None:
            break
        chain.append(
            DocumentRef(
                id=parent.id, code=parent.code, title=parent.title, doc_type=parent.doc_type
            )
        )
        parent_id = parent.parent_id
    return list(reversed(chain))


def approved_revision(db: Session, document_id: uuid.UUID) -> DocumentRevision | None:
    return db.scalar(
        select(DocumentRevision).where(
            DocumentRevision.document_id == document_id, DocumentRevision.status == rev.APPROVED
        )
    )


def open_revision(db: Session, document_id: uuid.UUID) -> DocumentRevision | None:
    return db.scalar(
        select(DocumentRevision).where(
            DocumentRevision.document_id == document_id,
            DocumentRevision.status.in_(rev.OPEN_STATUSES),
        )
    )


def list_revisions(db: Session, document_id: uuid.UUID) -> list[DocumentRevision]:
    return list(
        db.scalars(
            select(DocumentRevision)
            .where(DocumentRevision.document_id == document_id)
            .order_by(DocumentRevision.created_at.desc())
        )
    )


def _user_refs(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    ids.discard(None)
    if not ids:
        return {}
    users = db.scalars(select(AppUser).where(AppUser.id.in_(ids)))
    return {u.id: UserRef(id=u.id, name=u.name) for u in users}


def _meta_fields(r: DocumentRevision, users: dict[uuid.UUID, UserRef]) -> dict[str, Any]:
    return {
        "id": r.id,
        "document_id": r.document_id,
        "version": r.version,
        "status": r.status,
        "title": r.title,
        "change_kind": r.change_kind,
        "change_summary": r.change_summary,
        "author": users.get(r.author_id),
        "reviewer": users.get(r.reviewer_id),
        "review_comment": r.review_comment,
        "submitted_at": r.submitted_at,
        "reviewed_at": r.reviewed_at,
        "approved_at": r.approved_at,
        "content_hash": r.content_hash,
        "generated_by": r.generated_by,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def to_meta_list(db: Session, revisions: list[DocumentRevision]) -> list[RevisionMeta]:
    users = _user_refs(db, {x for r in revisions for x in (r.author_id, r.reviewer_id)})
    return [RevisionMeta(**_meta_fields(r, users)) for r in revisions]


def to_out(db: Session, r: DocumentRevision | None) -> RevisionOut | None:
    if r is None:
        return None
    users = _user_refs(db, {r.author_id, r.reviewer_id})
    return RevisionOut(
        **_meta_fields(r, users),
        sections=[Section(**s) for s in r.sections],
        structured=r.structured,
    )


# ── 생성 ─────────────────────────────────────────────────────────────────────


def _section_schema(db: Session, doc_type: str) -> list[dict[str, Any]]:
    type_def = db.get(DocTypeDef, doc_type)
    if type_def is None:
        raise api_error(422, "unknown_doc_type", f"알 수 없는 문서 유형입니다: {doc_type}")
    return type_def.sections


def _blank_sections(schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"key": s["key"], "title": s["title"], "body_md": (s.get("template") or "").rstrip()}
        for s in schema
    ]


def create_document(
    db: Session, *, system: ProcessSystem, payload: DocumentIn, actor_id: uuid.UUID
) -> Document:
    doc_type = payload.doc_type
    if doc_type not in DOC_TYPES:
        raise api_error(422, "unknown_doc_type", f"알 수 없는 문서 유형입니다: {doc_type}")
    schema = _section_schema(db, doc_type)

    parent: Document | None = None
    scope_code = payload.scope_code
    expected_parent = PARENT_TYPE.get(doc_type)

    if expected_parent:
        if payload.parent_id is None:
            raise api_error(
                422,
                "parent_required",
                f"{doc_type} 문서는 상위 {expected_parent} 문서가 필요합니다.",
            )
        parent = db.get(Document, payload.parent_id)
        if parent is not None and parent.system_id != system.id:
            # 하위 체계는 물려받은 문서 아래에도 문서를 추가할 수 있다.
            inherited = tailoring.find(db, system, parent.id)
            if inherited is None or inherited.state == "excluded":
                parent = None
        if parent is None:
            raise api_error(422, "parent_not_found", "상위 문서를 이 체계에서 찾을 수 없습니다.")
        if parent.doc_type != expected_parent:
            raise api_error(
                422,
                "parent_type_mismatch",
                f"{doc_type} 문서의 상위는 {expected_parent} 문서여야 합니다.",
            )
        scope_code = parent.scope_code
    else:
        if payload.parent_id is not None:
            raise api_error(
                422, "parent_not_allowed", f"{doc_type} 문서는 상위 문서를 갖지 않습니다."
            )
        if doc_type in SCOPED_ROOT_TYPES:
            if not scope_code:
                raise api_error(422, "scope_required", "영역코드를 선택하세요.")
            # 행 수준 보안으로 공통 코드와 이 회사의 코드만 보인다.
            if db.scalar(select(ScopeCode.id).where(ScopeCode.code == scope_code)) is None:
                raise api_error(422, "unknown_scope", f"등록되지 않은 영역코드입니다: {scope_code}")
        else:
            scope_code = None

    try:
        code = allocate_code(
            db,
            tenant_id=system.tenant_id,
            root_system_id=system.root_system_id,
            doc_type=doc_type,
            scope_code=scope_code,
            parent_code=parent.code if parent else None,
        )
    except ValueError as exc:
        raise api_error(422, "numbering_failed", f"문서 번호를 발급할 수 없습니다: {exc}") from exc

    doc = Document(
        tenant_id=system.tenant_id,
        system_id=system.id,
        doc_type=doc_type,
        code=code,
        scope_code=scope_code,
        title=payload.title,
        parent_id=parent.id if parent else None,
        created_by=actor_id,
    )
    db.add(doc)
    db.flush()
    db.add(
        DocumentRevision(
            tenant_id=system.tenant_id,
            document_id=doc.id,
            version=rev.target_version(None, "major"),
            status=rev.DRAFT,
            title=payload.title,
            sections=_blank_sections(schema),
            structured={},
            change_kind="major",
            change_summary="최초 제정",
            author_id=actor_id,
        )
    )
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="document.create",
        entity_type="document",
        entity_id=doc.id,
        data={"code": code, "title": payload.title, "system": system.slug},
    )
    return doc


def start_revision(
    db: Session, *, doc: Document, change_kind: str, change_summary: str, actor_id: uuid.UUID
) -> DocumentRevision:
    if open_revision(db, doc.id) is not None:
        raise api_error(409, "revision_in_progress", "이미 진행 중인 개정판이 있습니다.")
    current = approved_revision(db, doc.id)
    if current is None:
        raise api_error(409, "no_approved_revision", "승인된 판이 없어 개정을 시작할 수 없습니다.")

    revision = DocumentRevision(
        tenant_id=doc.tenant_id,
        document_id=doc.id,
        version=rev.target_version(current.version, change_kind),
        status=rev.DRAFT,
        title=current.title,
        sections=current.sections,
        structured=current.structured,
        change_kind=change_kind,
        change_summary=change_summary,
        based_on_revision_id=current.id,
        author_id=actor_id,
    )
    db.add(revision)
    db.flush()
    # 섹션별 근거 요건은 개정판에 묶여 있으므로 새 개정판이 물려받는다.
    for link in db.scalars(
        select(DocumentRequirement).where(DocumentRequirement.revision_id == current.id)
    ):
        db.add(
            DocumentRequirement(
                revision_id=revision.id,
                section_key=link.section_key,
                requirement_id=link.requirement_id,
                tenant_id=link.tenant_id,
                document_id=link.document_id,
            )
        )
    db.flush()
    audit.record(
        db,
        tenant_id=doc.tenant_id,
        actor_id=actor_id,
        action="revision.start",
        entity_type="document",
        entity_id=doc.id,
        data={"code": doc.code, "version": revision.version, "change_kind": change_kind},
    )
    return revision


# ── 편집 ─────────────────────────────────────────────────────────────────────


def _require_status(revision: DocumentRevision, *allowed: str) -> None:
    if revision.status not in allowed:
        raise api_error(
            409, "invalid_status", f"현재 상태({revision.status})에서는 할 수 없는 작업입니다."
        )


def update_revision(
    db: Session, *, revision: DocumentRevision, patch: RevisionPatch
) -> DocumentRevision:
    _require_status(revision, rev.DRAFT)
    doc = get_document(db, revision.document_id)

    if patch.title is not None:
        revision.title = patch.title
        if approved_revision(db, doc.id) is None:
            doc.title = patch.title  # 승인판이 없는 동안은 목록에 초안 제목을 보여준다

    if patch.sections is not None:
        schema = _section_schema(db, doc.doc_type)
        incoming = {s.key: s.body_md for s in patch.sections}
        unknown = set(incoming) - {s["key"] for s in schema}
        if unknown:
            raise api_error(
                422,
                "unknown_section",
                f"이 문서 유형에 없는 섹션입니다: {', '.join(sorted(unknown))}",
            )
        existing = {s["key"]: s.get("body_md", "") for s in revision.sections}
        # 섹션 구성과 순서는 항상 유형 정의를 따른다.
        revision.sections = [
            {
                "key": s["key"],
                "title": s["title"],
                "body_md": incoming.get(s["key"], existing.get(s["key"], "")),
            }
            for s in schema
        ]

    if patch.change_summary is not None:
        revision.change_summary = patch.change_summary

    if patch.change_kind is not None and patch.change_kind != revision.change_kind:
        current = approved_revision(db, doc.id)
        if current is None:
            raise api_error(422, "first_revision", "최초 제정판은 개정 구분을 바꿀 수 없습니다.")
        revision.change_kind = patch.change_kind
        revision.version = rev.target_version(current.version, patch.change_kind)

    db.flush()
    return revision


def discard_revision(db: Session, *, revision: DocumentRevision, actor_id: uuid.UUID) -> bool:
    """초안을 버린다. 승인판이 한 번도 없던 문서면 문서도 함께 지운다. 문서가 지워졌으면 True."""
    _require_status(revision, rev.DRAFT)
    doc = get_document(db, revision.document_id)
    never_approved = (
        db.scalar(
            select(func.count())
            .select_from(DocumentRevision)
            .where(
                DocumentRevision.document_id == doc.id,
                DocumentRevision.status.in_((rev.APPROVED, rev.SUPERSEDED)),
            )
        )
        == 0
    )
    if never_approved:
        has_children = db.scalar(select(Document.id).where(Document.parent_id == doc.id).limit(1))
        if has_children is not None:
            raise api_error(
                409,
                "has_children",
                "하위 문서가 있어 삭제할 수 없습니다. 하위 문서를 먼저 정리하세요.",
            )

    db.delete(revision)
    db.flush()
    if never_approved:
        db.delete(doc)
        db.flush()
    audit.record(
        db,
        tenant_id=doc.tenant_id,
        actor_id=actor_id,
        action="document.delete" if never_approved else "revision.discard",
        entity_type="document",
        entity_id=doc.id,
        data={"code": doc.code, "version": revision.version},
    )
    return never_approved


# ── 검토 흐름 ────────────────────────────────────────────────────────────────


def submit(db: Session, *, revision: DocumentRevision, actor_id: uuid.UUID) -> DocumentRevision:
    doc = get_document(db, revision.document_id)
    new_status = _transition(revision, "submit")

    missing = rev.missing_required_sections(revision.sections, _section_schema(db, doc.doc_type))
    if missing:
        raise api_error(
            422,
            "missing_sections",
            f"필수 섹션이 비어 있습니다: {', '.join(missing)}",
            sections=missing,
        )
    pending = list(dict.fromkeys(rev.open_decisions(revision.sections)))
    if pending:
        names = ", ".join(pending[:3]) + (" 등" if len(pending) > 3 else "")
        raise api_error(
            422,
            "open_decisions",
            f"조직이 정해야 할 항목이 남아 있습니다({names}). 채운 뒤 검토를 요청하세요.",
            decisions=pending,
        )
    revision.status = new_status
    revision.submitted_at = datetime.now(UTC)
    revision.review_comment = ""
    revision.content_hash = rev.content_hash(revision.title, revision.sections, revision.structured)
    db.flush()
    _audit_revision(db, doc, revision, actor_id, "revision.submit")
    return revision


def approve(
    db: Session,
    *,
    revision: DocumentRevision,
    actor_id: uuid.UUID,
    comment: str,
    tenant: Tenant,
    skipped_review: bool = False,
) -> DocumentRevision:
    """승인한다. skipped_review 는 검토 요청 단계 없이 초안에서 바로 승인했다는 표시(감사 기록)."""
    doc = get_document(db, revision.document_id)
    new_status = _transition(revision, "approve")
    _check_four_eyes(revision, actor_id, tenant)
    if doc.parent_id is not None and approved_revision(db, doc.parent_id) is None:
        parent = get_document(db, doc.parent_id)
        raise api_error(
            409,
            "parent_not_approved",
            f"상위 문서({parent.code})가 아직 승인되지 않았습니다. 상위 문서를 먼저 승인하세요.",
        )

    # 검토 중에는 내용을 고칠 수 없으므로 제출 때의 지문과 같아야 한다.
    if revision.content_hash != rev.content_hash(
        revision.title, revision.sections, revision.structured
    ):
        raise api_error(409, "content_changed", "제출 이후 내용이 달라졌습니다. 다시 제출하세요.")

    previous = approved_revision(db, doc.id)
    if previous is not None:
        previous.status = rev.next_status(previous.status, "supersede")
        db.flush()  # 문서당 승인판은 하나라는 유일 인덱스 때문에 먼저 반영한다

    now = datetime.now(UTC)
    revision.status = new_status
    revision.reviewer_id = actor_id
    revision.review_comment = comment
    revision.reviewed_at = now
    revision.approved_at = now
    doc.title = revision.title
    db.flush()
    extra = {"skipped_review": True} if skipped_review else {}
    _audit_revision(
        db, doc, revision, actor_id, "revision.approve", content_hash=revision.content_hash, **extra
    )
    return revision


def reject(
    db: Session,
    *,
    revision: DocumentRevision,
    actor_id: uuid.UUID,
    comment: str,
    tenant: Tenant,
) -> DocumentRevision:
    doc = get_document(db, revision.document_id)
    new_status = _transition(revision, "reject")
    _check_four_eyes(revision, actor_id, tenant)
    if not comment.strip():
        raise api_error(422, "comment_required", "반려 사유를 입력하세요.")

    revision.status = new_status
    revision.reviewer_id = actor_id
    revision.review_comment = comment.strip()
    revision.reviewed_at = datetime.now(UTC)
    db.flush()
    _audit_revision(db, doc, revision, actor_id, "revision.reject", comment=comment.strip())
    return revision


def withdraw(db: Session, *, revision: DocumentRevision, actor_id: uuid.UUID) -> DocumentRevision:
    doc = get_document(db, revision.document_id)
    revision.status = _transition(revision, "withdraw")
    revision.submitted_at = None
    db.flush()
    _audit_revision(db, doc, revision, actor_id, "revision.withdraw")
    return revision


def _transition(revision: DocumentRevision, action: str) -> str:
    try:
        return rev.next_status(revision.status, action)
    except rev.InvalidTransition:
        raise api_error(
            409, "invalid_status", f"현재 상태({revision.status})에서는 할 수 없는 작업입니다."
        ) from None


def four_eyes_enabled(tenant: Tenant) -> bool:
    return bool(tenant.settings.get("four_eyes", True))


def _check_four_eyes(revision: DocumentRevision, actor_id: uuid.UUID, tenant: Tenant) -> None:
    if (
        four_eyes_enabled(tenant)
        and revision.author_id is not None
        and violates_four_eyes(revision.author_id, actor_id)
    ):
        raise api_error(403, "four_eyes", "작성자는 자기 개정판을 검토할 수 없습니다.")


def _audit_revision(
    db: Session,
    doc: Document,
    revision: DocumentRevision,
    actor_id: uuid.UUID,
    action: str,
    **extra: Any,
) -> None:
    audit.record(
        db,
        tenant_id=doc.tenant_id,
        actor_id=actor_id,
        action=action,
        entity_type="revision",
        entity_id=revision.id,
        data={"code": doc.code, "version": revision.version, **extra},
    )
