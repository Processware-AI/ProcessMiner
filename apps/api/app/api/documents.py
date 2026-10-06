"""문서 라이브러리, 개정판 편집·검토, 받은 일."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import CommitRoute, get_db
from app.deps import TenantContext, current_user, tenant_context
from app.domain import revisions as rev
from app.domain.doc_types import allowed_child_types
from app.models import AppUser, DocTypeDef, Document, DocumentRevision, ProcessSystem
from app.schemas import (
    BatchItemResult,
    BatchReviewIn,
    BatchReviewOut,
    DecisionFillIn,
    DecisionFillOut,
    DecisionGroup,
    DocTypeOut,
    DocumentDetail,
    DocumentIn,
    DocumentRef,
    DocumentSummary,
    InboxItem,
    ReviewIn,
    RevisionMeta,
    RevisionOut,
    RevisionPatch,
    RevisionRef,
    RevisionStartIn,
    SectionSpec,
    SystemOut,
    SystemRef,
    TailoringIn,
    TailoringInfo,
)
from app.services import decisions as decision_svc
from app.services import documents as svc
from app.services import tailoring

router = APIRouter(prefix="/api", tags=["documents"], route_class=CommitRoute)


@router.get("/ref/doc-types", response_model=list[DocTypeOut])
def list_doc_types(
    _: AppUser = Depends(current_user), db: Session = Depends(get_db)
) -> list[DocTypeOut]:
    rows = db.scalars(select(DocTypeDef).order_by(DocTypeDef.sort))
    return [
        DocTypeOut(
            code=r.code,
            name=r.name,
            description=r.description,
            parent_type=r.parent_type,
            sections=[SectionSpec(**s) for s in r.sections],
        )
        for r in rows
    ]


# ── 문서 ─────────────────────────────────────────────────────────────────────


@router.get(
    "/t/{tenant_slug}/systems/{system_slug}/documents", response_model=list[DocumentSummary]
)
def list_documents(
    system_slug: str, ctx: TenantContext = Depends(tenant_context)
) -> list[DocumentSummary]:
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    return svc.list_documents(ctx.db, system)


@router.post(
    "/t/{tenant_slug}/systems/{system_slug}/documents",
    response_model=DocumentDetail,
    status_code=201,
)
def create_document(
    system_slug: str, payload: DocumentIn, ctx: TenantContext = Depends(tenant_context)
) -> DocumentDetail:
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.create", system.id)
    doc = svc.create_document(ctx.db, system=system, payload=payload, actor_id=ctx.user.id)
    return _detail(ctx, doc)


@router.get("/t/{tenant_slug}/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: uuid.UUID,
    system: str | None = None,
    ctx: TenantContext = Depends(tenant_context),
) -> DocumentDetail:
    """문서 한 건. system 을 주면 그 체계에서 보는 모습(상속·재정의·제외)으로 돌려준다."""
    doc = svc.get_document(ctx.db, document_id)
    ctx.require("doc.read", doc.system_id)
    return _detail(ctx, doc, ctx.system_by_slug(system) if system else None)


def _ref(doc: Document) -> DocumentRef:
    return DocumentRef(id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type)


def _detail(ctx: TenantContext, doc: Document, via: ProcessSystem | None = None) -> DocumentDetail:
    """via 는 문서를 보고 있는 체계다. 하위 체계에서 물려받은 문서를 볼 때 문서의 체계와 다르다."""
    db = ctx.db
    home = db.get(ProcessSystem, doc.system_id)
    view = via or home
    entries = {e.doc.id: e for e in tailoring.effective_documents(db, view)}
    if doc.id not in entries:
        # 그 체계에서 쓰이지 않는 문서(대체됐거나 상위에서 제외됨)는 문서 자신의 체계 기준으로 본다.
        view = home
        entries = {e.doc.id: e for e in tailoring.effective_documents(db, view)}
    entry = entries[doc.id]
    inherited = view.id != doc.system_id

    children = [e for e in entries.values() if e.parent_id == doc.id]
    summaries = {s.id: s for s in svc.effective_summaries(db, [entry, *children])}
    chain, parent_id = [], entry.parent_id
    while parent_id is not None:
        chain.append(_ref(entries[parent_id].doc))
        parent_id = entries[parent_id].parent_id

    approved = svc.approved_revision(db, doc.id)
    # 상위 체계에서 진행 중인 개정은 하위 체계에 보이지 않는다. 승인판만 내려온다.
    opened = None if inherited else svc.open_revision(db, doc.id)
    if inherited:
        actions = (
            [f"create_child:{t}" for t in allowed_child_types(doc.doc_type)]
            if entry.state == "inherited" and ctx.can("doc.create", view.id)
            else []
        )
    else:
        actions = _document_actions(ctx, doc, approved, opened)

    forked, current = tailoring.base_state(db, doc)
    base_changed = current is not None and (forked is None or forked.id != current.id)
    can_tailor = ctx.can("doc.tailor", view.id)
    tailoring_actions: list[str] = []
    if can_tailor and entry.state == "inherited":
        tailoring_actions = ["override", "exclude"] if approved is not None else ["exclude"]
    elif can_tailor and entry.state == "excluded" and not entry.implied:
        tailoring_actions = ["include"]
    elif can_tailor and entry.state == "override" and base_changed:
        tailoring_actions = ["ack_base"]
    base_home = db.get(ProcessSystem, entry.base.system_id) if entry.base is not None else None

    return DocumentDetail(
        document=summaries[doc.id],
        tailoring=TailoringInfo(
            state=entry.state,
            view_system=SystemRef(slug=view.slug, name=view.name),
            home_system=SystemRef(slug=home.slug, name=home.name),
            reason=entry.reason,
            implied=entry.implied,
            base=_ref(entry.base) if entry.base is not None else None,
            base_system=SystemRef(slug=base_home.slug, name=base_home.name) if base_home else None,
            base_forked=RevisionRef(id=forked.id, version=forked.version) if forked else None,
            base_current=RevisionRef(id=current.id, version=current.version) if current else None,
            base_changed=entry.state == "override" and base_changed,
            actions=tailoring_actions,
        ),
        system=SystemOut.model_validate(home),
        ancestors=list(reversed(chain)),
        children=sorted((summaries[c.doc.id] for c in children), key=lambda s: s.code),
        approved=svc.to_out(db, approved),
        open=svc.to_out(db, opened),
        actions=actions,
    )


# ── 테일러링 ─────────────────────────────────────────────────────────────────

_TAILORING = "/t/{tenant_slug}/systems/{system_slug}/tailoring/{document_id}"


@router.post(f"{_TAILORING}/override", response_model=DocumentDetail, status_code=201)
def override_document(
    system_slug: str,
    document_id: uuid.UUID,
    payload: TailoringIn,
    ctx: TenantContext = Depends(tenant_context),
) -> DocumentDetail:
    """상위 체계에서 물려받은 문서를 이 체계의 문서로 재정의한다."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.tailor", system.id)
    doc = tailoring.override(
        ctx.db, system=system, document_id=document_id, reason=payload.reason, actor_id=ctx.user.id
    )
    return _detail(ctx, doc)


@router.put(f"{_TAILORING}/exclusion", status_code=204)
def exclude_document(
    system_slug: str,
    document_id: uuid.UUID,
    payload: TailoringIn,
    ctx: TenantContext = Depends(tenant_context),
) -> None:
    """상위 체계에서 물려받은 문서를 이 체계에 적용하지 않는다."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.tailor", system.id)
    tailoring.exclude(
        ctx.db, system=system, document_id=document_id, reason=payload.reason, actor_id=ctx.user.id
    )


@router.delete(f"{_TAILORING}/exclusion", status_code=204)
def include_document(
    system_slug: str, document_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> None:
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.tailor", system.id)
    tailoring.include(ctx.db, system=system, document_id=document_id, actor_id=ctx.user.id)


@router.post("/t/{tenant_slug}/documents/{document_id}/ack-base", response_model=DocumentDetail)
def acknowledge_base_change(
    document_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> DocumentDetail:
    """재정의한 문서에서, 상위 문서의 변경을 확인했음을 남긴다."""
    doc = svc.get_document(ctx.db, document_id)
    ctx.require("doc.tailor", doc.system_id)
    tailoring.acknowledge_base(ctx.db, doc=doc, actor_id=ctx.user.id)
    return _detail(ctx, doc)


def _document_actions(
    ctx: TenantContext,
    doc: Document,
    approved: DocumentRevision | None,
    opened: DocumentRevision | None,
) -> list[str]:
    """요청자가 이 문서에서 지금 할 수 있는 일. 화면은 이 목록으로 버튼을 정한다."""
    sid = doc.system_id
    actions: list[str] = []
    if ctx.can("doc.create", sid):
        actions += [f"create_child:{t}" for t in allowed_child_types(doc.doc_type)]
    if opened is None:
        if approved is not None and ctx.can("doc.edit", sid):
            actions.append("start_revision")
    elif opened.status == rev.DRAFT:
        if ctx.can("doc.edit", sid):
            actions += ["edit", "discard"]
        if ctx.can("doc.submit", sid):
            actions.append("submit")
    elif opened.status == rev.IN_REVIEW:
        if opened.author_id == ctx.user.id or ctx.can("doc.edit", sid):
            actions.append("withdraw")
        own = svc.four_eyes_enabled(ctx.tenant) and opened.author_id == ctx.user.id
        if ctx.can("doc.review", sid) and not own:
            actions.append("review")
    return actions


# ── 개정판 ───────────────────────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/documents/{document_id}/revisions", response_model=list[RevisionMeta])
def list_revisions(
    document_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> list[RevisionMeta]:
    doc = svc.get_document(ctx.db, document_id)
    ctx.require("doc.read", doc.system_id)
    return svc.to_meta_list(ctx.db, svc.list_revisions(ctx.db, doc.id))


@router.post(
    "/t/{tenant_slug}/documents/{document_id}/revisions",
    response_model=RevisionOut,
    status_code=201,
)
def start_revision(
    document_id: uuid.UUID,
    payload: RevisionStartIn,
    ctx: TenantContext = Depends(tenant_context),
) -> RevisionOut:
    doc = svc.get_document(ctx.db, document_id)
    ctx.require("doc.edit", doc.system_id)
    revision = svc.start_revision(
        ctx.db,
        doc=doc,
        change_kind=payload.change_kind,
        change_summary=payload.change_summary,
        actor_id=ctx.user.id,
    )
    return svc.to_out(ctx.db, revision)


def _revision_for(
    ctx: TenantContext, revision_id: uuid.UUID, action: str
) -> tuple[DocumentRevision, Document]:
    revision = svc.get_revision(ctx.db, revision_id)
    doc = svc.get_document(ctx.db, revision.document_id)
    ctx.require(action, doc.system_id)
    return revision, doc


@router.get("/t/{tenant_slug}/revisions/{revision_id}", response_model=RevisionOut)
def get_revision(
    revision_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> RevisionOut:
    revision, _ = _revision_for(ctx, revision_id, "doc.read")
    return svc.to_out(ctx.db, revision)


@router.patch("/t/{tenant_slug}/revisions/{revision_id}", response_model=RevisionOut)
def update_revision(
    revision_id: uuid.UUID, payload: RevisionPatch, ctx: TenantContext = Depends(tenant_context)
) -> RevisionOut:
    revision, _ = _revision_for(ctx, revision_id, "doc.edit")
    return svc.to_out(ctx.db, svc.update_revision(ctx.db, revision=revision, patch=payload))


@router.delete("/t/{tenant_slug}/revisions/{revision_id}")
def discard_revision(
    revision_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> dict[str, bool]:
    revision, _ = _revision_for(ctx, revision_id, "doc.edit")
    deleted = svc.discard_revision(ctx.db, revision=revision, actor_id=ctx.user.id)
    return {"document_deleted": deleted}


@router.post("/t/{tenant_slug}/revisions/{revision_id}/submit", response_model=RevisionOut)
def submit_revision(
    revision_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> RevisionOut:
    revision, _ = _revision_for(ctx, revision_id, "doc.submit")
    return svc.to_out(ctx.db, svc.submit(ctx.db, revision=revision, actor_id=ctx.user.id))


@router.post("/t/{tenant_slug}/revisions/{revision_id}/approve", response_model=RevisionOut)
def approve_revision(
    revision_id: uuid.UUID, payload: ReviewIn, ctx: TenantContext = Depends(tenant_context)
) -> RevisionOut:
    revision, _ = _revision_for(ctx, revision_id, "doc.review")
    revision = svc.approve(
        ctx.db, revision=revision, actor_id=ctx.user.id, comment=payload.comment, tenant=ctx.tenant
    )
    return svc.to_out(ctx.db, revision)


@router.post("/t/{tenant_slug}/revisions/{revision_id}/reject", response_model=RevisionOut)
def reject_revision(
    revision_id: uuid.UUID, payload: ReviewIn, ctx: TenantContext = Depends(tenant_context)
) -> RevisionOut:
    revision, _ = _revision_for(ctx, revision_id, "doc.review")
    revision = svc.reject(
        ctx.db, revision=revision, actor_id=ctx.user.id, comment=payload.comment, tenant=ctx.tenant
    )
    return svc.to_out(ctx.db, revision)


@router.post("/t/{tenant_slug}/revisions/{revision_id}/withdraw", response_model=RevisionOut)
def withdraw_revision(
    revision_id: uuid.UUID, response: Response, ctx: TenantContext = Depends(tenant_context)
) -> RevisionOut:
    revision = svc.get_revision(ctx.db, revision_id)
    doc = svc.get_document(ctx.db, revision.document_id)
    if revision.author_id != ctx.user.id:
        ctx.require("doc.edit", doc.system_id)
    return svc.to_out(ctx.db, svc.withdraw(ctx.db, revision=revision, actor_id=ctx.user.id))


# ── 여러 건을 한 번에 ────────────────────────────────────────────────────────


@router.post("/t/{tenant_slug}/review-batch", response_model=BatchReviewOut)
def review_batch(
    payload: BatchReviewIn, ctx: TenantContext = Depends(tenant_context)
) -> BatchReviewOut:
    """여러 개정판을 한 번에 검토 요청하거나 승인한다.

    규칙은 한 건씩 할 때와 같고(권한, 작성자·검토자 분리, 상위 문서 먼저) 건마다 따로 판단한다.
    안 되는 건은 사유와 함께 돌려주고 나머지는 처리한다.
    """
    db = ctx.db
    ids = list(dict.fromkeys(payload.revision_ids))
    rows = db.execute(
        select(DocumentRevision, Document)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(DocumentRevision.id.in_(ids))
    ).all()
    found = {revision.id for revision, _ in rows}
    results = [
        BatchItemResult(revision_id=i, document=None, ok=False, error="개정판을 찾을 수 없습니다.")
        for i in ids
        if i not in found
    ]
    permission = "doc.submit" if payload.action == "submit" else "doc.review"
    # 상위 문서부터 처리한다. 상위가 승인돼야 하위를 승인할 수 있다.
    for revision, doc in sorted(rows, key=lambda row: (row[1].code.count("-"), row[1].code)):
        ref = DocumentRef(id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type)
        error = ""
        if not ctx.can(permission, doc.system_id):
            error = "이 문서를 처리할 권한이 없습니다."
        else:
            try:
                with db.begin_nested():
                    if payload.action == "submit":
                        svc.submit(db, revision=revision, actor_id=ctx.user.id)
                    else:
                        svc.approve(
                            db,
                            revision=revision,
                            actor_id=ctx.user.id,
                            comment=payload.comment,
                            tenant=ctx.tenant,
                        )
            except HTTPException as exc:
                detail = exc.detail
                error = detail.get("message", "") if isinstance(detail, dict) else str(detail)
                db.refresh(revision)
        results.append(
            BatchItemResult(revision_id=revision.id, document=ref, ok=not error, error=error)
        )
    done = sum(result.ok for result in results)
    return BatchReviewOut(done=done, failed=len(results) - done, results=results)


# ── 조직이 정해야 하는 항목 ──────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/systems/{system_slug}/decisions", response_model=list[DecisionGroup])
def list_decisions(
    system_slug: str, ctx: TenantContext = Depends(tenant_context)
) -> list[DecisionGroup]:
    """이 체계의 초안에 남아 있는 〔조직 결정: …〕 항목."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    return decision_svc.list_groups(ctx.db, system.id)


@router.post("/t/{tenant_slug}/systems/{system_slug}/decisions", response_model=DecisionFillOut)
def fill_decision(
    system_slug: str, payload: DecisionFillIn, ctx: TenantContext = Depends(tenant_context)
) -> DecisionFillOut:
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.edit", system.id)
    targets = (
        {(t.revision_id, t.section_key) for t in payload.targets}
        if payload.targets is not None
        else None
    )
    places, documents = decision_svc.fill(
        ctx.db,
        system=system,
        label=payload.label,
        value=payload.value,
        targets=targets,
        actor_id=ctx.user.id,
    )
    return DecisionFillOut(places=places, documents=documents)


# ── 받은 일 ──────────────────────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/inbox", response_model=list[InboxItem])
def inbox(ctx: TenantContext = Depends(tenant_context)) -> list[InboxItem]:
    """내가 검토할 개정판과 내가 작성 중인 개정판."""
    db = ctx.db
    rows = db.execute(
        select(DocumentRevision, Document, ProcessSystem)
        .join(Document, Document.id == DocumentRevision.document_id)
        .join(ProcessSystem, ProcessSystem.id == Document.system_id)
        .where(DocumentRevision.status.in_(rev.OPEN_STATUSES))
        .order_by(DocumentRevision.updated_at.desc())
    ).all()
    metas = {m.id: m for m in svc.to_meta_list(db, [r for r, _, _ in rows])}
    four_eyes = svc.four_eyes_enabled(ctx.tenant)

    items: list[InboxItem] = []
    for revision, doc, system in rows:
        mine = revision.author_id == ctx.user.id
        if revision.status == rev.IN_REVIEW:
            if ctx.can("doc.review", system.id) and not (four_eyes and mine):
                kind = "to_review"
            elif mine:
                kind = "my_in_review"
            else:
                continue
        elif mine:
            kind = "returned" if revision.review_comment else "my_draft"
        else:
            continue
        items.append(
            InboxItem(
                kind=kind,
                document=DocumentRef(
                    id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type
                ),
                system_slug=system.slug,
                system_name=system.name,
                revision=metas[revision.id],
            )
        )
    return items
