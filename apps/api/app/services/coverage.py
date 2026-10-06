"""표준 커버리지: 체계가 근거로 삼은 표준의 요건이 어느 문서에서 이행되는가.

따로 저장하는 표가 아니라 그때그때 센다. 근거는 문서의 섹션이 요건을 인용한 링크
(document_requirement)뿐이다. 요건의 상태는 그 요건을 인용한 문서로 정해진다.
  covered  승인된 판이 인용한다(조직의 기준으로 이행하고 있다)
  drafted  아직 승인되지 않은 판만 인용한다
  gap      어느 문서도 인용하지 않는다
  excluded 이 체계에 적용하지 않기로 했다(사유가 있다)

심사에서는 여기에 실제로 수행한 기록을 잇는다(요건 → 문서 → 기록). 기록은 그 요건을 인용한
양식(템플릿), 또는 그 요건을 인용한 지침에 딸린 양식으로 발행한 것이다. 기간을 주면 그 기간에
수행한(수행일이 없으면 발행한) 기록만 센다.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import revisions as rev
from app.models import (
    DocTypeDef,
    Document,
    DocumentRequirement,
    DocumentRevision,
    ProcessRecord,
    ProcessSystem,
    SourceClause,
)
from app.schemas import (
    CoverageChapter,
    CoverageDocument,
    CoverageOut,
    CoverageRecord,
    CoverageRequirement,
    CoverageSource,
    SourceRef,
)
from app.services import basis as basis_svc
from app.services import tailoring

# 한 문서에 승인판과 진행 중인 판이 함께 있으면 승인판을 앞세운다.
_STATE_ORDER = {rev.APPROVED: 0, rev.IN_REVIEW: 1, rev.DRAFT: 2}


def _chapter_key(clause_number: str) -> str:
    """요건이 속한 장. "5.1.1" → "5", 부속서의 "F.2" → "F"."""
    return clause_number.removeprefix("Annex ").split(".")[0]


def _records_by_template(
    db: Session, system: ProcessSystem, date_from: date | None, date_to: date | None
) -> dict:
    """발행한 기록을 양식 문서별로 묶는다. 기간을 주면 그 기간에 수행한 기록만."""
    by_template: dict = {}
    for record in db.scalars(
        select(ProcessRecord)
        .where(ProcessRecord.system_id == system.id, ProcessRecord.status == "published")
        .order_by(ProcessRecord.code)
    ):
        when = record.performed_on or (record.published_at.date() if record.published_at else None)
        if date_from and (when is None or when < date_from):
            continue
        if date_to and (when is None or when > date_to):
            continue
        by_template.setdefault(record.template_document_id, []).append(
            CoverageRecord(
                id=record.id,
                code=record.code or "",
                title=record.title,
                performed_on=when,
                legacy=record.legacy,
                artifact_id=record.artifact_id,
            )
        )
    return by_template


def system_coverage(
    db: Session,
    system: ProcessSystem,
    date_from: date | None = None,
    date_to: date | None = None,
) -> CoverageOut:
    section_titles = {
        row.code: {s["key"]: s["title"] for s in row.sections}
        for row in db.scalars(select(DocTypeDef))
    }

    # 이 체계에서 쓰이는 문서만 센다: 자기 문서와 물려받은 문서. 제외한 문서는 빠진다.
    entries = [e for e in tailoring.effective_documents(db, system) if e.state != "excluded"]
    effective = {e.doc.id for e in entries}
    # 재정의했지만 아직 승인하지 않은 문서는, 승인할 때까지 상위 문서의 승인판이 유효하다.
    overrides = {e.doc.id: e.base.id for e in entries if e.base is not None}
    approved_overrides = (
        set(
            db.scalars(
                select(DocumentRevision.document_id).where(
                    DocumentRevision.document_id.in_(overrides),
                    DocumentRevision.status == rev.APPROVED,
                )
            )
        )
        if overrides
        else set()
    )
    standing_bases = {
        base for doc_id, base in overrides.items() if doc_id not in approved_overrides
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
        .where(
            Document.id.in_(effective | standing_bases),
            DocumentRevision.status.in_(_STATE_ORDER),
        )
        .order_by(Document.code)
    )
    for requirement_id, section_key, status, doc in links:
        if doc.id not in effective and status != rev.APPROVED:
            continue
        by_state = cited.setdefault(requirement_id, {}).setdefault(
            doc.id, {"doc": doc, "states": {}}
        )
        by_state["states"].setdefault(status, []).append(section_key)

    # 양식 → 기록. 요건을 인용한 문서가 양식이면 그 기록, 지침이면 그 아래 양식들의 기록이다.
    records_by_template = _records_by_template(db, system, date_from, date_to)
    forms_under: dict = {}
    for entry in entries:
        if entry.doc.doc_type == "TMP" and entry.parent_id is not None:
            forms_under.setdefault(entry.parent_id, []).append(entry.doc.id)

    def records_for(documents: list[CoverageDocument]) -> list[CoverageRecord]:
        found: dict = {}
        for document in documents:
            forms = (
                [document.id] if document.doc_type == "TMP" else forms_under.get(document.id, [])
            )
            for form in forms:
                for record in records_by_template.get(form, []):
                    found[record.id] = record
        return sorted(found.values(), key=lambda r: r.code)

    # 근거(적용요건)는 상위 체계의 것까지 물려받는다. 요건 제외는 근거를 정한 체계의 것을 따른다.
    bases, seen = [], set()
    for level in tailoring.lineage(db, system):
        for basis, source, _total, _excluded in basis_svc.list_basis(db, level.id):
            if source.id not in seen:
                seen.add(source.id)
                bases.append((level, basis, source))

    sources = []
    for level, basis, source in bases:
        chapters: dict[str, str] = {}
        for number, title, kind in db.execute(
            select(SourceClause.number, SourceClause.title, SourceClause.kind)
            .where(SourceClause.source_id == source.id, SourceClause.level == 1)
            .order_by(SourceClause.position)
        ):
            # 프로세스 체계는 프로세스 그룹(SWE, SYS …)으로 묶는다. 그룹에는 제목이 없다.
            chapters.setdefault(_chapter_key(number), "" if kind == "process" else title)
        requirements = []
        for requirement, clause, exclusion in basis_svc.requirements_with_exclusions(
            db, level.id, source.id
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
                    records=records_for(documents) if exclusion is None else [],
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
                evidenced=sum(bool(r.records) for r in requirements),
                chapters=[CoverageChapter(key=key, title=chapters.get(key, "")) for key in used],
                requirements=requirements,
            )
        )
    return CoverageOut(sources=sources, date_from=date_from, date_to=date_to)


# ── 심사 증적 묶음 ───────────────────────────────────────────────────────────

_STATUS_LABEL = {"covered": "이행", "drafted": "초안", "gap": "미이행", "excluded": "제외"}
_DOC_STATE = {"approved": "승인", "in_review": "검토 중", "draft": "초안"}
_OBLIGATION = {"shall": "필수", "should": "권고", "may": "허용"}


def audit_pack_xlsx(coverage: CoverageOut, system_name: str, tenant_name: str) -> bytes:
    """표준별 시트에 요건 → 이행 문서 → 기록을 한 줄씩 담는다. 첫 시트는 요약이다."""
    from app.export.xlsx import Sheet, build

    period = (
        f"{coverage.date_from or '처음'} ~ {coverage.date_to or '지금'}"
        if coverage.date_from or coverage.date_to
        else "전체 기간"
    )
    summary: list[list] = [
        ["항목", "값"],
        ["회사", tenant_name],
        ["체계", system_name],
        ["기록 기간", period],
        ["", ""],
        ["표준", "적용 요건 / 이행 / 초안 / 미이행 / 제외 / 기록 있음"],
    ]
    sheets = []
    for source in coverage.sources:
        applicable = source.total - source.excluded
        summary.append(
            [
                f"{source.source.code} {source.source.title}",
                f"{applicable} / {source.covered} / {source.drafted} / {source.gaps} / "
                f"{source.excluded} / {source.evidenced}",
            ]
        )
        titles = {c.key: c.title for c in source.chapters}
        rows: list[list] = [
            ["장", "조항", "요건", "의무", "요건 요약", "상태"]
            + ["이행 문서", "기록(증적)", "제외 사유"]
        ]
        for r in source.requirements:
            rows.append(
                [
                    f"{r.chapter} {titles.get(r.chapter, '')}".strip(),
                    r.clause_number,
                    r.code,
                    _OBLIGATION.get(r.obligation, r.obligation),
                    r.summary,
                    _STATUS_LABEL[r.status],
                    chr(10).join(
                        f"{d.code} {d.title} ({_DOC_STATE[d.state]}: {', '.join(d.sections)})"
                        for d in r.documents
                    ),
                    chr(10).join(
                        f"{rec.code} {rec.title}"
                        + (f" ({rec.performed_on})" if rec.performed_on else "")
                        + (" [기존 산출물]" if rec.legacy else "")
                        for rec in r.records
                    ),
                    r.reason,
                ]
            )
        sheets.append(Sheet(source.source.code, rows, widths=[22, 9, 12, 7, 50, 8, 55, 45, 30]))
    return build([Sheet("요약", summary, widths=[40, 60]), *sheets])
