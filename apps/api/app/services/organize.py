"""문서 정리: 삭제·폐지·되살리기, 체계 안에서 위치 바꾸기, 다른 체계로 복사·옮기기.

승인판은 지울 수 없다(document_revision_guard). 그래서 '삭제'는 문서마다 둘 중 하나가 된다.
  삭제  승인된 적이 없고 무엇도 이 문서를 가리키지 않으면, 문서와 초안을 지운다.
  폐지  그 밖의 문서. 개정 이력은 남고, 체계의 문서 목록·커버리지·상속에서 빠진다.
하위 문서도 같은 규칙으로 함께 정리한다.

다른 체계로 옮기기는 대상 체계에 새 번호로 복사한 뒤 원본을 위 규칙으로 정리한다.
원본의 승인 이력은 원래 번호 그대로 남고, 복사본은 대상 체계에서 다시 승인받는다.
같은 체계 안에서 위치를 바꾸면 문서와 이력은 그대로 두고 번호만 새 상위 문서 기준으로 다시 받는다.

호출 전에 세션에 회사가 지정돼 있어야 한다(행 수준 보안). 권한 확인은 라우터가 한다.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import revisions as rev
from app.domain.doc_types import PARENT_TYPE
from app.errors import api_error
from app.models import (
    Document,
    DocumentRequirement,
    DocumentRevision,
    ProcessRecord,
    ProcessSystem,
)
from app.schemas import DocumentIn
from app.services import audit, tailoring
from app.services import documents as doc_service
from app.services.numbering import allocate_code


@dataclass
class Removal:
    deleted: list[Document] = field(default_factory=list)
    retired: list[Document] = field(default_factory=list)


# ── 조회 도우미 ──────────────────────────────────────────────────────────────


def subtree(db: Session, roots: list[Document], *, include_retired: bool = False) -> list[Document]:
    """roots 와 그 하위 문서 전부. 상위 문서가 하위 문서보다 앞에 온다."""
    seen: dict[uuid.UUID, Document] = {}
    queue = list(roots)
    while queue:
        doc = queue.pop(0)
        if doc.id in seen:
            continue
        seen[doc.id] = doc
        query = select(Document).where(Document.parent_id == doc.id)
        if not include_retired:
            query = query.where(Document.retired_at.is_(None))
        queue.extend(db.scalars(query.order_by(Document.code)))
    return list(seen.values())


def top_level(db: Session, docs: list[Document]) -> list[Document]:
    """고른 문서 가운데, 상위 문서가 함께 골라지지 않은 것만. 하위 문서는 상위를 따라간다."""
    chosen = {doc.id for doc in docs}
    result = []
    for doc in docs:
        parent_id, nested = doc.parent_id, False
        while parent_id is not None:
            if parent_id in chosen:
                nested = True
                break
            parent_id = db.scalar(select(Document.parent_id).where(Document.id == parent_id))
        if not nested:
            result.append(doc)
    return result


def _ever_approved(db: Session, document_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(DocumentRevision)
            .where(
                DocumentRevision.document_id == document_id,
                DocumentRevision.status.in_((rev.APPROVED, rev.SUPERSEDED)),
            )
        )
    )


def _referenced(db: Session, document_id: uuid.UUID) -> bool:
    """이 문서를 가리키는 기록이나 하위 체계의 재정의가 있는가(있으면 지울 수 없다)."""
    record = db.scalar(
        select(ProcessRecord.id).where(ProcessRecord.template_document_id == document_id).limit(1)
    )
    override = db.scalar(select(Document.id).where(Document.overrides_id == document_id).limit(1))
    return record is not None or override is not None


def _clear_open_revision(db: Session, doc: Document) -> None:
    """진행 중인 개정판을 버린다. 검토 중이면 초안으로 되돌린 뒤 지운다(초안만 지울 수 있다)."""
    opened = doc_service.open_revision(db, doc.id)
    if opened is None:
        return
    if opened.status == rev.IN_REVIEW:
        opened.status = rev.DRAFT
        db.flush()
    db.delete(opened)
    db.flush()


def _usable_parent(
    db: Session, system: ProcessSystem, parent_id: uuid.UUID | None, doc_type: str
) -> Document | None:
    """doc_type 문서를 system 에서 parent_id 아래에 둘 수 있는지 확인하고 상위 문서를 돌려준다."""
    expected = PARENT_TYPE.get(doc_type)
    if expected is None:
        if parent_id is not None:
            raise api_error(
                422, "parent_not_allowed", f"{doc_type} 문서는 상위 문서를 갖지 않습니다."
            )
        return None
    if parent_id is None:
        raise api_error(
            422, "parent_required", f"{doc_type} 문서는 상위 {expected} 문서 아래에 둬야 합니다."
        )
    parent = db.get(Document, parent_id)
    if parent is not None and parent.system_id != system.id:
        # 하위 체계에서는 물려받은 문서 아래에도 둘 수 있다.
        entry = tailoring.find(db, system, parent.id)
        if entry is None or entry.state == "excluded":
            parent = None
    if parent is None or parent.retired_at is not None:
        raise api_error(422, "parent_not_found", "상위 문서를 대상 체계에서 찾을 수 없습니다.")
    if parent.doc_type != expected:
        raise api_error(
            422,
            "parent_type_mismatch",
            f"{doc_type} 문서의 상위는 {expected} 문서여야 합니다.",
        )
    return parent


# ── 삭제·폐지·되살리기 ────────────────────────────────────────────────────────


def plan_removal(db: Session, docs: list[Document]) -> tuple[list[Document], set[uuid.UUID]]:
    """정리할 문서(하위 포함, 상위가 앞)와, 그 가운데 지울 수 있는 문서 id."""
    targets = subtree(db, docs)
    deletable: set[uuid.UUID] = set()
    # 하위 문서부터 본다. 하위 문서가 하나라도 남으면 상위 문서도 지울 수 없다.
    for doc in reversed(targets):
        children = db.scalars(select(Document.id).where(Document.parent_id == doc.id)).all()
        if (
            not _ever_approved(db, doc.id)
            and not _referenced(db, doc.id)
            and all(child in deletable for child in children)
        ):
            deletable.add(doc.id)
    return targets, deletable


def remove(
    db: Session,
    *,
    docs: list[Document],
    reason: str,
    actor_id: uuid.UUID,
    enforce_reason: bool = True,
) -> Removal:
    """문서와 그 하위 문서를 지우거나 폐지한다."""
    targets, deletable = plan_removal(db, docs)
    result = Removal(
        deleted=[doc for doc in targets if doc.id in deletable],
        retired=[doc for doc in targets if doc.id not in deletable],
    )
    reason = reason.strip()
    if result.retired and not reason and enforce_reason:
        raise api_error(
            422,
            "reason_required",
            "승인된 적이 있는 문서는 이력을 남기고 폐지합니다. 폐지 사유를 입력하세요.",
        )

    now = datetime.now(UTC)
    for doc in result.retired:
        _clear_open_revision(db, doc)
        doc.retired_at, doc.retired_by, doc.retire_reason = now, actor_id, reason
        audit.record(
            db,
            tenant_id=doc.tenant_id,
            actor_id=actor_id,
            action="document.retire",
            entity_type="document",
            entity_id=doc.id,
            data={"code": doc.code, "title": doc.title, "reason": reason},
        )
    db.flush()

    for doc in reversed(result.deleted):
        _clear_open_revision(db, doc)
        audit.record(
            db,
            tenant_id=doc.tenant_id,
            actor_id=actor_id,
            action="document.delete",
            entity_type="document",
            entity_id=doc.id,
            data={"code": doc.code, "title": doc.title},
        )
        db.delete(doc)
        db.flush()
    return result


def restore(db: Session, *, doc: Document, actor_id: uuid.UUID) -> list[Document]:
    """폐지한 문서를 되살린다. 함께 폐지된 하위 문서도 되살린다."""
    if doc.retired_at is None:
        raise api_error(409, "not_retired", "폐지한 문서가 아닙니다.")
    parent = db.get(Document, doc.parent_id) if doc.parent_id else None
    if parent is not None and parent.retired_at is not None:
        raise api_error(
            409, "parent_retired", "상위 문서가 폐지돼 있습니다. 상위 문서부터 되살리세요."
        )
    batch = doc.retired_at
    restored = [d for d in subtree(db, [doc], include_retired=True) if d.retired_at == batch]
    for d in restored:
        d.retired_at, d.retired_by, d.retire_reason = None, None, ""
        audit.record(
            db,
            tenant_id=d.tenant_id,
            actor_id=actor_id,
            action="document.restore",
            entity_type="document",
            entity_id=d.id,
            data={"code": d.code, "title": d.title},
        )
    db.flush()
    return restored


# ── 체계 안에서 위치 바꾸기 ────────────────────────────────────────────────────


def reparent(
    db: Session,
    *,
    system: ProcessSystem,
    docs: list[Document],
    parent_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> list[tuple[Document, str]]:
    """같은 체계 안에서 상위 문서를 바꾼다. 번호는 새 상위 문서 기준으로 다시 받는다.

    (문서, 이전 번호) 목록을 돌려준다. 하위 문서도 번호가 바뀌므로 함께 들어 있다.
    """
    moved: list[tuple[Document, str]] = []
    for root in top_level(db, docs):
        if PARENT_TYPE.get(root.doc_type) is None:
            raise api_error(
                422,
                "cannot_reparent",
                f"{root.doc_type} 문서는 상위 문서가 없어 위치를 옮길 수 없습니다.",
            )
        parent = _usable_parent(db, system, parent_id, root.doc_type)
        if parent.id == root.parent_id:
            continue
        root.parent_id = parent.id
        # 하위 문서의 번호는 상위 번호에서 나오므로 폐지한 문서까지 모두 다시 매긴다.
        new_code = {parent.id: parent.code}
        for doc in subtree(db, [root], include_retired=True):
            old = doc.code
            doc.code = allocate_code(
                db,
                tenant_id=system.tenant_id,
                root_system_id=system.root_system_id,
                doc_type=doc.doc_type,
                scope_code=parent.scope_code,
                parent_code=new_code[doc.parent_id],
            )
            doc.scope_code = parent.scope_code
            new_code[doc.id] = doc.code
            db.flush()
            moved.append((doc, old))
            audit.record(
                db,
                tenant_id=doc.tenant_id,
                actor_id=actor_id,
                action="document.move",
                entity_type="document",
                entity_id=doc.id,
                data={"from_code": old, "to_code": doc.code, "system": system.slug},
            )
    return moved


# ── 복사 ─────────────────────────────────────────────────────────────────────


def copy(
    db: Session,
    *,
    target: ProcessSystem,
    docs: list[Document],
    parent_id: uuid.UUID | None,
    include_children: bool,
    actor_id: uuid.UUID,
) -> list[tuple[Document, Document]]:
    """문서를 target 체계에 새 번호의 초안으로 복사한다. (원본, 복사본) 목록을 돌려준다.

    내용은 진행 중인 개정판이 있으면 그것을, 없으면 승인판을 옮긴다. 섹션별 근거 요건도 함께 옮긴다.
    """
    roots = top_level(db, docs) if include_children else docs
    for root in roots:
        _usable_parent(db, target, parent_id, root.doc_type)

    copies: dict[uuid.UUID, Document] = {}
    pairs: list[tuple[Document, Document]] = []
    for root in roots:
        sources = subtree(db, [root]) if include_children else [root]
        for source in sources:
            is_root = source.id == root.id
            title = source.title
            if is_root and source.system_id == target.id:
                title = f"{title} (사본)"[:300]
            new = doc_service.create_document(
                db,
                system=target,
                payload=DocumentIn(
                    doc_type=source.doc_type,
                    title=title,
                    scope_code=source.scope_code
                    if PARENT_TYPE.get(source.doc_type) is None
                    else None,
                    parent_id=parent_id if is_root else copies[source.parent_id].id,
                ),
                actor_id=actor_id,
            )
            _copy_content(db, source=source, copy_of=new, title=title)
            copies[source.id] = new
            pairs.append((source, new))
            audit.record(
                db,
                tenant_id=new.tenant_id,
                actor_id=actor_id,
                action="document.copy",
                entity_type="document",
                entity_id=new.id,
                data={"from_code": source.code, "to_code": new.code, "system": target.slug},
            )

    # 작성예시는 양식을 가리킨다. 양식도 함께 복사했으면 복사본을 가리키게 한다.
    for source, new in pairs:
        draft = doc_service.open_revision(db, new.id)
        form_id = draft.structured.get("example_of") if draft else None
        if not form_id:
            continue
        form_copy = copies.get(uuid.UUID(form_id))
        structured = dict(draft.structured)
        if form_copy is not None:
            structured["example_of"] = str(form_copy.id)
        elif source.system_id != target.id:
            structured.pop("example_of")
        draft.structured = structured
    db.flush()
    return pairs


def _copy_content(db: Session, *, source: Document, copy_of: Document, title: str) -> None:
    working = doc_service.open_revision(db, source.id) or doc_service.approved_revision(
        db, source.id
    )
    draft = doc_service.open_revision(db, copy_of.id)
    if working is None or draft is None:
        return
    draft.title = title
    draft.sections = working.sections
    draft.structured = dict(working.structured)
    draft.generated_by = working.generated_by
    draft.change_summary = f"{source.code} 에서 복사"
    db.flush()
    for link in db.scalars(
        select(DocumentRequirement).where(DocumentRequirement.revision_id == working.id)
    ):
        db.add(
            DocumentRequirement(
                revision_id=draft.id,
                section_key=link.section_key,
                requirement_id=link.requirement_id,
                tenant_id=link.tenant_id,
                document_id=copy_of.id,
            )
        )
    db.flush()
