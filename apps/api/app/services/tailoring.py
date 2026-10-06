"""테일러링: 하위 체계가 상위 체계의 문서를 어떻게 쓰는가.

하위 체계는 상위 체계의 문서를 물려받고, 문서마다 넷 중 하나의 상태를 갖는다.
  inherited  상위 문서를 그대로 쓴다(기본). 상위 문서가 개정되면 따라간다.
  override   이 체계의 문서로 대체한다. 상위 문서의 승인판에서 갈라져 자기 개정 이력을 갖는다.
  excluded   이 체계에는 적용하지 않는다. 사유가 있어야 한다.
  added      이 체계에만 있는 문서.
최상위(기준선) 체계의 문서는 모두 own 이다.

한 체계에서 실제로 쓰이는 문서 집합은 effective_documents 한 곳에서 계산한다.
문서 목록, 커버리지, 이후의 정합화·심사가 모두 이 함수를 거친다.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import revisions as rev
from app.errors import api_error, not_found
from app.models import (
    Document,
    DocumentExclusion,
    DocumentRequirement,
    DocumentRevision,
    ProcessSystem,
)
from app.services import audit


@dataclass
class Effective:
    """한 체계에서 쓰이는 문서 하나와 그 테일러링 상태."""

    doc: Document  # 실제로 쓰이는 문서. 상속·제외면 상위 체계의 문서다.
    state: str  # own | inherited | override | added | excluded
    home: ProcessSystem  # doc 이 속한 체계
    base: Document | None = None  # override 가 대체한 상위 문서
    reason: str = ""  # 재정의·제외 사유
    parent_id: uuid.UUID | None = None  # 이 체계의 문서 계층에서의 상위 문서
    implied: bool = False  # 상위 문서가 제외돼 함께 제외된 문서


def lineage(db: Session, system: ProcessSystem) -> list[ProcessSystem]:
    """이 체계부터 최상위 체계까지."""
    chain = [system]
    while chain[-1].parent_system_id is not None:
        chain.append(db.get(ProcessSystem, chain[-1].parent_system_id))
    return chain


def effective_documents(db: Session, system: ProcessSystem) -> list[Effective]:
    """이 체계에서 쓰이는 문서를 번호 순으로. 제외한 문서도 사유와 함께 들어 있다."""
    entries: dict[uuid.UUID, Effective] = {}
    # 대체된 문서 id → 지금 그 자리를 차지한 문서 id
    replaced: dict[uuid.UUID, uuid.UUID] = {}

    def resolve(document_id: uuid.UUID | None) -> uuid.UUID | None:
        while document_id in replaced:
            document_id = replaced[document_id]
        return document_id

    def under_excluded(entry: Effective) -> bool:
        parent = entries.get(entry.parent_id)
        return parent is not None and (parent.state == "excluded" or under_excluded(parent))

    for level in reversed(lineage(db, system)):
        is_root = level.parent_system_id is None
        # 상위 체계가 제외한 문서는 내려오지 않는다. 내려온 문서는 일단 모두 '상속'이다.
        entries = {key: entry for key, entry in entries.items() if entry.state != "excluded"}
        for entry in entries.values():
            entry.state, entry.base, entry.reason = "inherited", None, ""

        own = db.scalars(select(Document).where(Document.system_id == level.id))
        for doc in own:
            target = resolve(doc.overrides_id)
            if target is not None and target in entries:
                base = entries.pop(target)
                replaced[target] = doc.id
                entries[doc.id] = Effective(
                    doc, "override", level, base=base.doc, reason=doc.tailoring_reason
                )
            else:
                entries[doc.id] = Effective(doc, "own" if is_root else "added", level)

        for exclusion in db.scalars(
            select(DocumentExclusion).where(DocumentExclusion.system_id == level.id)
        ):
            entry = entries.get(resolve(exclusion.document_id))
            if entry is not None and entry.state == "inherited":
                entry.state, entry.reason = "excluded", exclusion.reason

        for entry in entries.values():
            parent_id = resolve(entry.doc.parent_id)
            entry.parent_id = parent_id if parent_id in entries else None
        # 상위 문서를 제외하면 그 아래 문서도 함께 빠진다(그 아래 체계로도 내려가지 않는다).
        for entry in entries.values():
            if entry.state == "inherited" and under_excluded(entry):
                entry.state, entry.implied = "excluded", True

    return sorted(entries.values(), key=lambda entry: entry.doc.code)


def find(db: Session, system: ProcessSystem, document_id: uuid.UUID) -> Effective | None:
    return next(
        (e for e in effective_documents(db, system) if e.doc.id == document_id),
        None,
    )


def _inherited(db: Session, system: ProcessSystem, document_id: uuid.UUID) -> Effective:
    """테일러링할 수 있는 문서(상위에서 물려받아 그대로 쓰고 있는 문서)를 찾는다."""
    if system.parent_system_id is None:
        raise api_error(409, "baseline_system", "기준선 체계의 문서는 테일러링 대상이 아닙니다.")
    entry = find(db, system, document_id)
    if entry is None:
        raise not_found("문서")
    if entry.state != "inherited":
        raise api_error(
            409, "not_inherited", "상위 체계에서 물려받아 그대로 쓰는 문서만 바꿀 수 있습니다."
        )
    return entry


def _require_reason(reason: str) -> str:
    reason = reason.strip()
    if not reason:
        raise api_error(
            422, "reason_required", "사유를 입력하세요. 심사에서 왜 다른지 설명해야 합니다."
        )
    return reason


def approved_revision(db: Session, document_id: uuid.UUID) -> DocumentRevision | None:
    return db.scalar(
        select(DocumentRevision).where(
            DocumentRevision.document_id == document_id, DocumentRevision.status == rev.APPROVED
        )
    )


def override(
    db: Session, *, system: ProcessSystem, document_id: uuid.UUID, reason: str, actor_id: uuid.UUID
) -> Document:
    """상위 문서를 이 체계의 문서로 재정의한다. 상위 승인판을 복사한 초안에서 시작한다."""
    entry = _inherited(db, system, document_id)
    reason = _require_reason(reason)
    base = entry.doc
    current = approved_revision(db, base.id)
    if current is None:
        raise api_error(
            409,
            "base_not_approved",
            "상위 문서가 아직 승인되지 않았습니다. 승인된 문서만 재정의할 수 있습니다.",
        )

    doc = Document(
        tenant_id=system.tenant_id,
        system_id=system.id,
        doc_type=base.doc_type,
        code=base.code,  # 같은 자리의 문서이므로 번호를 그대로 쓴다
        scope_code=base.scope_code,
        title=current.title,
        parent_id=base.parent_id,
        overrides_id=base.id,
        base_revision_id=current.id,
        tailoring_reason=reason,
        created_by=actor_id,
    )
    db.add(doc)
    db.flush()
    revision = DocumentRevision(
        tenant_id=system.tenant_id,
        document_id=doc.id,
        version=rev.target_version(None, "major"),
        status=rev.DRAFT,
        title=current.title,
        sections=current.sections,
        structured=current.structured,
        change_kind="major",
        change_summary=f"상위 문서 {base.code} v{current.version} 에서 재정의: {reason}",
        based_on_revision_id=current.id,
        author_id=actor_id,
    )
    db.add(revision)
    db.flush()
    # 섹션별 근거 요건도 물려받는다(재정의해도 어느 요건을 이행하는지는 이어진다).
    for link in db.scalars(
        select(DocumentRequirement).where(DocumentRequirement.revision_id == current.id)
    ):
        db.add(
            DocumentRequirement(
                revision_id=revision.id,
                section_key=link.section_key,
                requirement_id=link.requirement_id,
                tenant_id=system.tenant_id,
                document_id=doc.id,
            )
        )
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="tailoring.override",
        entity_type="document",
        entity_id=doc.id,
        data={
            "system": system.slug,
            "code": base.code,
            "base_version": current.version,
            "reason": reason,
        },
    )
    return doc


def exclude(
    db: Session, *, system: ProcessSystem, document_id: uuid.UUID, reason: str, actor_id: uuid.UUID
) -> None:
    """상위 문서를 이 체계에 적용하지 않는다. 그 아래 문서도 함께 빠진다."""
    entry = _inherited(db, system, document_id)
    reason = _require_reason(reason)

    # 이 체계가 그 아래에 재정의하거나 추가한 문서가 있으면 먼저 정리해야 한다.
    entries = {e.doc.id: e for e in effective_documents(db, system)}

    def is_under(candidate: Effective) -> bool:
        parent = entries.get(candidate.parent_id)
        return parent is not None and (parent.doc.id == entry.doc.id or is_under(parent))

    blocking = [e for e in entries.values() if e.state in ("override", "added") and is_under(e)]
    if blocking:
        raise api_error(
            409,
            "has_own_documents",
            f"이 문서 아래에 이 체계가 재정의하거나 추가한 문서가 있습니다"
            f"({blocking[0].doc.code}). 그 문서를 먼저 정리하세요.",
        )

    db.add(
        DocumentExclusion(
            system_id=system.id,
            document_id=entry.doc.id,
            tenant_id=system.tenant_id,
            reason=reason,
            excluded_by=actor_id,
        )
    )
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="tailoring.exclude",
        entity_type="document",
        entity_id=entry.doc.id,
        data={"system": system.slug, "code": entry.doc.code, "reason": reason},
    )


def include(
    db: Session, *, system: ProcessSystem, document_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """제외를 되돌려 다시 상위 문서를 그대로 쓴다."""
    exclusion = db.get(DocumentExclusion, {"system_id": system.id, "document_id": document_id})
    if exclusion is None:
        raise not_found("제외한 문서")
    doc = db.get(Document, document_id)
    db.delete(exclusion)
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="tailoring.include",
        entity_type="document",
        entity_id=document_id,
        data={"system": system.slug, "code": doc.code if doc else ""},
    )


def base_state(
    db: Session, doc: Document
) -> tuple[DocumentRevision | None, DocumentRevision | None]:
    """재정의 문서가 기준으로 삼은 상위 판과, 상위 문서의 지금 승인판."""
    if doc.overrides_id is None:
        return None, None
    forked = db.get(DocumentRevision, doc.base_revision_id) if doc.base_revision_id else None
    return forked, approved_revision(db, doc.overrides_id)


def acknowledge_base(db: Session, *, doc: Document, actor_id: uuid.UUID) -> Document:
    """상위 문서의 변경을 확인했음을 남긴다(반영했거나, 반영하지 않기로 했거나).

    이후에는 상위 문서가 다시 개정될 때까지 '상위 변경됨' 표시가 사라진다.
    """
    forked, current = base_state(db, doc)
    if doc.overrides_id is None or current is None:
        raise api_error(409, "not_an_override", "상위 문서를 재정의한 문서가 아닙니다.")
    if forked is not None and forked.id == current.id:
        raise api_error(409, "base_unchanged", "상위 문서가 바뀌지 않았습니다.")
    doc.base_revision_id = current.id
    db.flush()
    audit.record(
        db,
        tenant_id=doc.tenant_id,
        actor_id=actor_id,
        action="tailoring.sync",
        entity_type="document",
        entity_id=doc.id,
        data={
            "code": doc.code,
            "from_version": forked.version if forked else None,
            "to_version": current.version,
            "at": datetime.now(UTC).isoformat(),
        },
    )
    return doc
