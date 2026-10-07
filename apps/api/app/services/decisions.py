"""조직이 정해야 하는 항목.

표준에서 생성한 초안에는 표준이 값을 정하지 않아 조직이 스스로 정해야 하는 곳이
〔조직 결정: 무엇을 정해야 하는지〕 로 표시돼 있다. 이 표시가 남은 문서는 기준이 될 수 없으므로
검토를 요청할 수 없다. 여기서는 한 체계의 초안에 남은 항목을 모아 보여주고, 값을 채운다.
누가 언제 무엇을 정했는지는 개정판(structured.decisions)과 감사 기록에 남긴다.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import revisions as rev
from app.errors import api_error
from app.llm import LLMError
from app.models import Document, DocumentRevision, ProcessSystem, Run, RunEvent, Tenant
from app.pipelines import decide
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


# ── AI 로 한꺼번에 채우기 ────────────────────────────────────────────────────

AI_RUN_KIND = "fill_decisions"
_BATCH = 40  # 한 번의 모델 호출로 채우는 자리 수(문서 단위로 묶는다)


def _occurrence_id(revision_id: uuid.UUID, section_key: str, index: int) -> str:
    return f"{revision_id}|{section_key}|{index}"


def latest_ai_run(db: Session, system_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run)
        .where(Run.kind == AI_RUN_KIND, Run.progress["system_id"].astext == str(system_id))
        .order_by(Run.created_at.desc())
        .limit(1)
    )


def start_ai_fill(db: Session, *, system: ProcessSystem, actor_id: uuid.UUID) -> Run:
    """이 체계의 초안에 남은 항목을 모델이 모두 채우도록 작업을 건다."""
    run = latest_ai_run(db, system.id)
    if run is not None and run.status in ("queued", "running"):
        raise api_error(409, "run_in_progress", "이미 채우고 있습니다.")
    if not list_groups(db, system.id):
        raise api_error(409, "nothing_to_fill", "채울 항목이 남아 있지 않습니다.")
    run = Run(
        tenant_id=system.tenant_id,
        kind=AI_RUN_KIND,
        status="queued",
        progress={"system_id": str(system.id)},
        started_by=actor_id,
    )
    db.add(run)
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="decision.ai_fill",
        entity_type="system",
        entity_id=system.id,
        data={"system": system.slug},
    )
    return run


def _blanks(revision: DocumentRevision, doc: Document) -> list[decide.Blank]:
    blanks = []
    for section in revision.sections:
        for index, found in enumerate(rev.find_decisions(section.get("body_md") or "")):
            blanks.append(
                decide.Blank(
                    id=_occurrence_id(revision.id, section["key"], index),
                    label=found.label,
                    document=f"{doc.code} {doc.title}",
                    section=section["title"],
                    before=found.before,
                    after=found.after,
                )
            )
    return blanks


def _apply(
    revision: DocumentRevision,
    decided: dict[str, decide.Decided],
    expected: dict[str, str],
    model: str,
) -> int:
    """한 개정판의 자리들을 채운다. 그사이 본문이 바뀌어 자리가 맞지 않으면 그 자리는 건너뛴다."""
    now = datetime.now(UTC).isoformat()
    sections, records = [], []
    filled = 0
    for section in revision.sections:
        key = section["key"]
        position = -1

        def replace(match, key=key):
            nonlocal position, filled
            position += 1
            occurrence = _occurrence_id(revision.id, key, position)
            item = decided.get(occurrence)
            if item is None or expected.get(occurrence) != match.group(1):
                return match.group(0)
            filled += 1
            records.append(
                {
                    "section_key": key,
                    "label": match.group(1),
                    "value": item.value,
                    "decided_by": None,
                    "by": "ai",
                    "model": model,
                    "rationale": item.rationale.strip(),
                    "decided_at": now,
                }
            )
            return item.value

        body = rev.DECISION_PATTERN.sub(replace, section.get("body_md") or "")
        sections.append({**section, "body_md": body})
    if filled:
        revision.sections = sections
        revision.structured = {
            **revision.structured,
            "decisions": [*revision.structured.get("decisions", []), *records],
        }
    return filled


def _log(db: Session, run: Run, message: str) -> None:
    db.add(RunEvent(tenant_id=run.tenant_id, run_id=run.id, level="info", message=message))


def run_ai_fill(db: Session, run: Run) -> None:
    """작업자가 부른다. 문서 단위로 묶어 모델에 묻고, 묶음이 끝날 때마다 반영한다."""
    system = db.get(ProcessSystem, uuid.UUID(run.progress["system_id"]))
    tenant = db.get(Tenant, system.tenant_id)
    drafts = [(r, d, _blanks(r, d)) for r, d in _drafts(db, system.id)]
    drafts = [item for item in drafts if item[2]]
    total = sum(len(blanks) for _, _, blanks in drafts)

    # 이 체계에서 사람이 이미 정한 값은 일관되게 쓰도록 보여준다.
    known: dict[str, str] = {}
    for revision in db.scalars(
        select(DocumentRevision)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(Document.system_id == system.id)
    ):
        for record in revision.structured.get("decisions", []):
            if record.get("by") != "ai":
                known.setdefault(record["label"], record["value"])

    batches: list[list] = [[]]
    for item in drafts:
        size = sum(len(blanks) for _, _, blanks in batches[-1])
        if batches[-1] and size + len(item[2]) > _BATCH:
            batches.append([])
        batches[-1].append(item)
    progress = {**run.progress, "total": total, "done": 0, "failed": 0}
    progress.update(input_tokens=0, output_tokens=0)
    run.progress = dict(progress)
    _log(db, run, f"문서 {len(drafts)}건의 {total}곳을 채웁니다")
    db.commit()

    context = f"회사: {tenant.name}\n체계: {system.name}"
    if system.description:
        context += f" — {system.description}"
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, get_settings().llm_concurrency)) as pool:
        futures = {
            pool.submit(
                decide.decide, [b for _, _, blanks in batch for b in blanks], context, known
            ): batch
            for batch in batches
            if batch
        }
        for future in as_completed(futures):
            batch = futures[future]
            try:
                decided, result = future.result()
            except LLMError as exc:
                errors.append(str(exc))
                progress["failed"] += sum(len(blanks) for _, _, blanks in batch)
            else:
                progress["input_tokens"] += result.input_tokens
                progress["output_tokens"] += result.output_tokens
                for revision, _doc, blanks in batch:
                    db.refresh(revision)
                    if revision.status != rev.DRAFT:
                        progress["failed"] += len(blanks)
                        continue
                    expected = {b.id: b.label for b in blanks}
                    filled = _apply(revision, decided, expected, result.model)
                    progress["done"] += filled
                    progress["failed"] += len(blanks) - filled
            run.progress = dict(progress)
            db.commit()

    run.finished_at = datetime.now(UTC)
    if progress["done"] == 0:
        run.status = "failed"
        run.error = errors[0] if errors else "채운 곳이 없습니다."
    else:
        run.status = "succeeded"
        message = f"{progress['done']}곳을 채웠습니다"
        if progress["failed"]:
            message += f" ({progress['failed']}곳은 채우지 못했습니다)"
        _log(db, run, message)
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=run.started_by,
        action="decision.ai_filled",
        entity_type="system",
        entity_id=system.id,
        data={"system": system.slug, "places": progress["done"], "failed": progress["failed"]},
    )
    db.commit()


def ai_filled(db: Session, system_id: uuid.UUID) -> list[dict]:
    """초안에 모델이 채운 값. 사람이 검토할 수 있게 문서·자리·근거와 함께 돌려준다."""
    rows = []
    for revision, doc in _drafts(db, system_id):
        titles = {s["key"]: s["title"] for s in revision.sections}
        ref = DocumentRef(id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type)
        for record in revision.structured.get("decisions", []):
            if record.get("by") == "ai":
                rows.append(
                    {
                        "revision_id": revision.id,
                        "document": ref,
                        "section_title": titles.get(record["section_key"], record["section_key"]),
                        "label": record["label"],
                        "value": record["value"],
                        "rationale": record.get("rationale", ""),
                        "decided_at": record["decided_at"],
                    }
                )
    return rows
