"""표준 커버리지: 체계가 근거로 삼은 표준의 요건이 어느 문서에서 이행되는가.

따로 저장하는 표가 아니라 그때그때 센다. 근거는 문서의 섹션이 요건을 인용한 링크
(document_requirement)뿐이다. 요건의 상태는 그 요건을 인용한 문서로 정해진다.
  covered  승인된 판이 인용한다(조직의 기준으로 이행하고 있다)
  drafted  아직 승인되지 않은 판만 인용한다
  gap      어느 문서도 인용하지 않는다
  excluded 이 체계에 적용하지 않기로 했다(사유가 있다)
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import revisions as rev
from app.models import (
    DocTypeDef,
    Document,
    DocumentRequirement,
    DocumentRevision,
    ProcessSystem,
    SourceClause,
)
from app.schemas import (
    CoverageChapter,
    CoverageDocument,
    CoverageOut,
    CoverageRequirement,
    CoverageSource,
    SourceRef,
)
from app.services import basis as basis_svc

# 한 문서에 승인판과 진행 중인 판이 함께 있으면 승인판을 앞세운다.
_STATE_ORDER = {rev.APPROVED: 0, rev.IN_REVIEW: 1, rev.DRAFT: 2}


def _chapter_key(clause_number: str) -> str:
    """요건이 속한 장. "5.1.1" → "5", 부속서의 "F.2" → "F"."""
    return clause_number.removeprefix("Annex ").split(".")[0]


def system_coverage(db: Session, system: ProcessSystem) -> CoverageOut:
    section_titles = {
        row.code: {s["key"]: s["title"] for s in row.sections}
        for row in db.scalars(select(DocTypeDef))
    }

    # 요건 → 문서 → (판의 상태, 인용한 섹션). 대체된 옛 판은 세지 않는다.
    cited: dict = {}
    links = db.execute(
        select(
            DocumentRequirement.requirement_id,
            DocumentRequirement.section_key,
            DocumentRevision.status,
            Document,
        )
        .join(DocumentRevision, DocumentRevision.id == DocumentRequirement.revision_id)
        .join(Document, Document.id == DocumentRequirement.document_id)
        .where(Document.system_id == system.id, DocumentRevision.status.in_(_STATE_ORDER))
        .order_by(Document.code)
    )
    for requirement_id, section_key, status, doc in links:
        by_state = cited.setdefault(requirement_id, {}).setdefault(
            doc.id, {"doc": doc, "states": {}}
        )
        by_state["states"].setdefault(status, []).append(section_key)

    sources = []
    for basis, source, _total, _excluded in basis_svc.list_basis(db, system.id):
        chapters = {
            _chapter_key(number): title
            for number, title in db.execute(
                select(SourceClause.number, SourceClause.title)
                .where(SourceClause.source_id == source.id, SourceClause.level == 1)
                .order_by(SourceClause.position)
            )
        }
        requirements = []
        for requirement, clause, exclusion in basis_svc.requirements_with_exclusions(
            db, system.id, source.id
        ):
            documents = []
            for entry in cited.get(requirement.id, {}).values():
                doc, states = entry["doc"], entry["states"]
                state = min(states, key=_STATE_ORDER.__getitem__)
                titles = section_titles.get(doc.doc_type, {})
                documents.append(
                    CoverageDocument(
                        id=doc.id,
                        code=doc.code,
                        title=doc.title,
                        doc_type=doc.doc_type,
                        state=state,
                        sections=[titles.get(key, key) for key in dict.fromkeys(states[state])],
                    )
                )
            if exclusion is not None:
                status = "excluded"
            elif any(d.state == rev.APPROVED for d in documents):
                status = "covered"
            elif documents:
                status = "drafted"
            else:
                status = "gap"
            requirements.append(
                CoverageRequirement(
                    id=requirement.id,
                    code=requirement.code,
                    clause_number=clause.number,
                    chapter=_chapter_key(clause.number),
                    obligation=requirement.obligation,
                    summary=requirement.summary,
                    status=status,
                    reason=exclusion.reason if exclusion else "",
                    documents=documents,
                )
            )

        def count(status: str, rows: list[CoverageRequirement] = requirements) -> int:
            return sum(r.status == status for r in rows)

        used = list(dict.fromkeys(r.chapter for r in requirements))
        sources.append(
            CoverageSource(
                source=SourceRef(
                    id=source.id, code=source.code, title=source.title, edition=source.edition
                ),
                approved_at=basis.approved_at,
                total=len(requirements),
                excluded=count("excluded"),
                covered=count("covered"),
                drafted=count("drafted"),
                gaps=count("gap"),
                chapters=[CoverageChapter(key=key, title=chapters.get(key, "")) for key in used],
                requirements=requirements,
            )
        )
    return CoverageOut(sources=sources)
