"""문서 라이브러리, 개정판 편집·검토, 받은 일."""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import CommitRoute, get_db
from app.deps import TenantContext, current_user, tenant_context
from app.domain import revisions as rev
from app.domain.doc_types import allowed_child_types
from app.models import AppUser, DocTypeDef, Document, DocumentRevision, ProcessSystem
from app.schemas import (
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
    RevisionStartIn,
    SectionSpec,
    SystemOut,
)
from app.services import documents as svc

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
    return svc.list_documents(ctx.db, system.id)


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
    document_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> DocumentDetail:
    doc = svc.get_document(ctx.db, document_id)
    ctx.require("doc.read", doc.system_id)
    return _detail(ctx, doc)


def _detail(ctx: TenantContext, doc: Document) -> DocumentDetail:
    db = ctx.db
    approved = svc.approved_revision(db, doc.id)
    opened = svc.open_revision(db, doc.id)
    return DocumentDetail(
        document=svc.get_summary(db, doc.id),
        system=SystemOut.model_validate(db.get(ProcessSystem, doc.system_id)),
        ancestors=svc.ancestors(db, doc),
        children=svc.list_children(db, doc.id),
        approved=svc.to_out(db, approved),
        open=svc.to_out(db, opened),
        actions=_document_actions(ctx, doc, approved, opened),
    )


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
