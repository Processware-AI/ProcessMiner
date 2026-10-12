"""문서 정리: 삭제·폐지·되살리기, 위치 바꾸기, 다른 체계로 옮기기·복사."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.db import CommitRoute
from app.deps import TenantContext, tenant_context
from app.errors import api_error
from app.models import Document
from app.schemas import (
    CopiedRef,
    DocumentRef,
    DocumentSummary,
    MovedRef,
    OrganizeOut,
    RelocateIn,
    RemoveIn,
    SystemRef,
)
from app.services import documents as doc_service
from app.services import organize

router = APIRouter(prefix="/api", tags=["documents"], route_class=CommitRoute)


def _ref(doc: Document) -> DocumentRef:
    return DocumentRef(id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type)


def _load(ctx: TenantContext, ids: list[uuid.UUID]) -> list[Document]:
    docs = list(ctx.db.scalars(select(Document).where(Document.id.in_(set(ids)))))
    if len(docs) != len(set(ids)):
        raise api_error(404, "not_found", "문서를 찾을 수 없습니다.")
    retired = [doc.code for doc in docs if doc.retired_at is not None]
    if retired:
        raise api_error(
            409, "document_retired", f"폐지한 문서는 정리할 수 없습니다: {', '.join(retired)}"
        )
    return sorted(docs, key=lambda doc: doc.code)


@router.get(
    "/t/{tenant_slug}/systems/{system_slug}/documents/retired",
    response_model=list[DocumentSummary],
)
def list_retired(
    system_slug: str, ctx: TenantContext = Depends(tenant_context)
) -> list[DocumentSummary]:
    """이 체계에서 폐지한 문서."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    return doc_service.list_retired(ctx.db, system)


@router.post("/t/{tenant_slug}/documents/remove", response_model=OrganizeOut)
def remove_documents(
    payload: RemoveIn, ctx: TenantContext = Depends(tenant_context)
) -> OrganizeOut:
    """승인된 적 없는 문서는 지우고, 나머지는 폐지한다. 하위 문서도 함께."""
    docs = _load(ctx, payload.document_ids)
    for system_id in {doc.system_id for doc in docs}:
        ctx.require("doc.manage", system_id)

    with ctx.db.begin_nested() as savepoint:
        result = organize.remove(
            ctx.db,
            docs=docs,
            reason=payload.reason,
            actor_id=ctx.user.id,
            enforce_reason=not payload.dry_run,
        )
        out = OrganizeOut(
            dry_run=payload.dry_run,
            deleted=[_ref(doc) for doc in result.deleted],
            retired=[_ref(doc) for doc in result.retired],
        )
        if payload.dry_run:
            savepoint.rollback()
    return out


@router.post("/t/{tenant_slug}/documents/{document_id}/restore", response_model=OrganizeOut)
def restore_document(
    document_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> OrganizeOut:
    doc = doc_service.get_document(ctx.db, document_id)
    ctx.require("doc.manage", doc.system_id)
    restored = organize.restore(ctx.db, doc=doc, actor_id=ctx.user.id)
    return OrganizeOut(dry_run=False, restored=[_ref(d) for d in restored])


@router.post("/t/{tenant_slug}/documents/relocate", response_model=OrganizeOut)
def relocate_documents(
    payload: RelocateIn, ctx: TenantContext = Depends(tenant_context)
) -> OrganizeOut:
    """문서를 옮기거나 복사한다.

    같은 체계로 옮기면 위치(상위 문서)만 바꾸고 번호를 다시 받는다. 다른 체계로 옮기면 그 체계에
    새 번호로 복사한 뒤 원본을 지우거나 폐지한다. 복사는 원본을 그대로 둔다.
    """
    db = ctx.db
    docs = _load(ctx, payload.document_ids)
    target = ctx.system_by_slug(payload.target_system)
    ctx.require("doc.create", target.id)
    homes = {doc.system_id for doc in docs}
    if payload.mode == "move":
        if len(homes) > 1:
            raise api_error(422, "mixed_systems", "한 체계의 문서만 함께 옮길 수 있습니다.")
        ctx.require("doc.manage", next(iter(homes)))
    else:
        for system_id in homes:
            ctx.require("doc.read", system_id)

    out = OrganizeOut(
        dry_run=payload.dry_run, target_system=SystemRef(slug=target.slug, name=target.name)
    )
    with db.begin_nested() as savepoint:
        if payload.mode == "move" and homes == {target.id}:
            moved = organize.reparent(
                db, system=target, docs=docs, parent_id=payload.parent_id, actor_id=ctx.user.id
            )
            out.moved = [MovedRef(document=_ref(doc), old_code=old) for doc, old in moved]
        else:
            # 옮기기는 하위 문서가 항상 따라간다. 상위만 옮기면 남은 하위 문서가 갈 곳이 없다.
            include_children = payload.include_children or payload.mode == "move"
            pairs = organize.copy(
                db,
                target=target,
                docs=docs,
                parent_id=payload.parent_id,
                include_children=include_children,
                actor_id=ctx.user.id,
            )
            out.created = [CopiedRef(source=_ref(src), document=_ref(new)) for src, new in pairs]
            if payload.mode == "move":
                reason = payload.reason.strip() or f"{target.name}(으)로 옮김"
                removal = organize.remove(
                    db,
                    docs=organize.top_level(db, docs),
                    reason=reason,
                    actor_id=ctx.user.id,
                )
                out.deleted = [_ref(doc) for doc in removal.deleted]
                out.retired = [_ref(doc) for doc in removal.retired]
        if payload.dry_run:
            savepoint.rollback()
    return out
