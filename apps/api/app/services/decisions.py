"""조직이 정해야 하는 항목.

표준에서 생성한 초안에는 표준이 값을 정하지 않아 조직이 스스로 정해야 하는 곳이
〔조직 결정: 무엇을 정해야 하는지〕 로 표시돼 있다. 이 표시가 남은 문서는 기준이 될 수 없으므로
검토를 요청할 수 없다. 여기서는 한 체계의 초안에 남은 항목을 모아 보여주고, 값을 채운다.
누가 언제 무엇을 정했는지는 개정판(structured.decisions)과 감사 기록에 남긴다.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import revisions as rev
from app.errors import api_error
from app.models import Document, DocumentRevision, ProcessSystem
from app.schemas import DecisionGroup, DecisionOccurrence, DocumentRef
from app.services import audit


def _drafts(db: Session, system_id: uuid.UUID) -> list[tuple[DocumentRevision, Document]]:
    return list(
        db.execute(
            select(DocumentRevision, Document)
            .join(Document, Document.id == DocumentRevision.document_id)
            .where(Document.system_id == system_id, DocumentRevision.status == rev.DRAFT)
            .order_by(Document.code)
        ).all()
    )


def list_groups(db: Session, system_id: uuid.UUID) -> list[DecisionGroup]:
    """초안에 남은 항목을 이름별로 묶는다. 여러 곳에 나오는 항목이 먼저 온다."""
    groups: dict[str, list[DecisionOccurrence]] = {}
    for revision, doc in _drafts(db, system_id):
        ref = DocumentRef(id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type)
        for section in revision.sections:
            for found in rev.find_decisions(section.get("body_md") or ""):
                groups.setdefault(found.label, []).append(
                    DecisionOccurrence(
                        revision_id=revision.id,
                        document=ref,
                        section_key=section["key"],
                        section_title=section["title"],
                        before=found.before,
                        after=found.after,
                    )
                )
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[1][0].document.code))
    return [DecisionGroup(label=label, occurrences=found) for label, found in ordered]


def fill(
    db: Session,
    *,
    system: ProcessSystem,
    label: str,
    value: str,
    targets: set[tuple[uuid.UUID, str]] | None,
    actor_id: uuid.UUID,
) -> tuple[int, int]:
    """항목에 값을 채운다. targets 가 없으면 이 체계의 초안 전체에서 같은 이름의 항목을 모두 채운다.

    (채운 곳 수, 바뀐 문서 수)를 돌려준다.
    """
    label, value = label.strip(), value.strip()
    if not value:
        raise api_error(422, "value_required", "정한 내용을 입력하세요.")
    if "〔" in value or "〕" in value:
        raise api_error(422, "invalid_value", "정한 내용에는 〔 〕 기호를 쓸 수 없습니다.")

    now = datetime.now(UTC).isoformat()
    places, codes = 0, []
    for revision, doc in _drafts(db, system.id):
        sections, decided = [], []
        for section in revision.sections:
            body = section.get("body_md") or ""
            if targets is None or (revision.id, section["key"]) in targets:
                body, count = rev.fill_decision(body, label, value)
                if count:
                    places += count
                    decided.append(
                        {
                            "section_key": section["key"],
                            "label": label,
                            "value": value,
                            "decided_by": str(actor_id),
                            "decided_at": now,
                        }
                    )
            sections.append({**section, "body_md": body})
        if decided:
            revision.sections = sections
            revision.structured = {
                **revision.structured,
                "decisions": [*revision.structured.get("decisions", []), *decided],
            }
            codes.append(doc.code)
    if places == 0:
        raise api_error(
            409, "nothing_to_fill", "채울 항목을 찾지 못했습니다. 화면을 새로 고치세요."
        )

    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="decision.fill",
        entity_type="system",
        entity_id=system.id,
        data={
            "system": system.slug,
            "label": label,
            "value": value[:500],
            "places": places,
            "documents": codes[:50],
        },
    )
    return places, len(codes)
