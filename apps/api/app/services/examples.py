"""작성예시(EX) 만들기.

이 체계의 양식(템플릿)마다 작성예시가 없으면 모델이 쓴다. 작성예시는 양식과 같은 지침 아래에
두고, 어느 양식의 예시인지 개정판에 남긴다(structured.example_of). 작성예시는 교육용이라
기록 양식으로 고를 수 없다(기록은 템플릿으로만 만든다).
"""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import api_error
from app.llm import LLMError
from app.models import (
    DocTypeDef,
    Document,
    DocumentRequirement,
    DocumentRevision,
    ProcessSystem,
    Requirement,
    Run,
    RunEvent,
    SourceDocument,
)
from app.pipelines import examples, harmonize
from app.schemas import DocumentIn
from app.services import audit, tailoring
from app.services import documents as doc_service

RUN_KIND = "write_examples"


def _working(db: Session, document_id: uuid.UUID) -> DocumentRevision | None:
    return doc_service.open_revision(db, document_id) or doc_service.approved_revision(
        db, document_id
    )


def missing(db: Session, system: ProcessSystem) -> list[tuple[Document, Document]]:
    """작성예시가 없는 (양식, 상위 지침). 이 체계가 고칠 수 있는 지침 아래의 양식만 본다."""
    entries = {e.doc.id: e for e in tailoring.effective_documents(db, system)}
    own = {"own", "override", "added"}
    covered: set[str] = set()
    for entry in entries.values():
        if entry.doc.doc_type == "EX" and entry.state != "excluded":
            revision = _working(db, entry.doc.id)
            if revision is not None and revision.structured.get("example_of"):
                covered.add(revision.structured["example_of"])
    result = []
    for entry in sorted(entries.values(), key=lambda e: e.doc.code):
        parent = entries.get(entry.parent_id)
        if (
            entry.doc.doc_type == "TMP"
            and entry.state != "excluded"
            and str(entry.doc.id) not in covered
            and parent is not None
            and parent.state in own
            and parent.doc.system_id == system.id
        ):
            result.append((entry.doc, parent.doc))
    return result


def latest_run(db: Session, system_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run)
        .where(Run.kind == RUN_KIND, Run.progress["system_id"].astext == str(system_id))
        .order_by(Run.created_at.desc())
        .limit(1)
    )


def start(db: Session, *, system: ProcessSystem, actor_id: uuid.UUID) -> Run:
    run = latest_run(db, system.id)
    if run is not None and run.status in ("queued", "running"):
        raise api_error(409, "run_in_progress", "이미 작성예시를 만들고 있습니다.")
    if not missing(db, system):
        raise api_error(409, "nothing_to_write", "작성예시가 없는 양식이 없습니다.")
    run = Run(
        tenant_id=system.tenant_id,
        kind=RUN_KIND,
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
        action="example.write",
        entity_type="system",
        entity_id=system.id,
        data={"system": system.slug},
    )
    return run


def _task(db: Session, form: Document, instruction: Document, schema: list[dict]):
    form_revision = _working(db, form.id)
    wi_revision = _working(db, instruction.id)
    if form_revision is None or wi_revision is None:
        return None
    guide = next((s["body_md"] for s in form_revision.sections if s["key"] == "guide"), "")
    steps = "\n\n".join(
        f"## {s['title']}\n{s['body_md']}" for s in wi_revision.sections if s.get("body_md")
    )
    requirements = [
        f"{code} {r.code}: {r.summary}"
        for code, r in db.execute(
            select(SourceDocument.code, Requirement)
            .join(Requirement, Requirement.source_id == SourceDocument.id)
            .join(DocumentRequirement, DocumentRequirement.requirement_id == Requirement.id)
            .where(DocumentRequirement.revision_id == wi_revision.id)
            .distinct()
        )
    ][:20]
    return examples.ExampleTask(
        template_title=form.title,
        template_guide=guide or "",
        fields=harmonize.template_fields(form_revision.sections),
        instruction_title=instruction.title,
        instruction_steps=steps,
        requirements=requirements,
        section_schema=schema,
    )


def run_write(db: Session, run: Run) -> None:
    """작업자가 부른다. 양식마다 작성예시를 써서 초안 문서로 저장한다."""

    def log(message: str, level: str = "info") -> None:
        db.add(RunEvent(tenant_id=run.tenant_id, run_id=run.id, level=level, message=message))

    system = db.get(ProcessSystem, uuid.UUID(run.progress["system_id"]))
    schema = db.get(DocTypeDef, "EX").sections
    targets = missing(db, system)
    tasks = [(form, wi, _task(db, form, wi, schema)) for form, wi in targets]
    tasks = [t for t in tasks if t[2] is not None and t[2].fields]
    progress = {**run.progress, "total": len(tasks), "done": 0, "failed": 0}
    progress.update(input_tokens=0, output_tokens=0)
    run.progress = dict(progress)
    log(f"양식 {len(tasks)}건의 작성예시를 씁니다")
    db.commit()

    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, get_settings().llm_concurrency)) as pool:
        futures = {pool.submit(examples.write, task): (form, wi) for form, wi, task in tasks}
        for future in as_completed(futures):
            form, wi = futures[future]
            try:
                sections, result = future.result()
                with db.begin_nested():
                    document = doc_service.create_document(
                        db,
                        system=system,
                        payload=DocumentIn(
                            doc_type="EX", title=f"{form.title} 작성예시"[:300], parent_id=wi.id
                        ),
                        actor_id=run.started_by,
                    )
                    revision = doc_service.open_revision(db, document.id)
                    revision.sections = sections
                    revision.structured = {"example_of": str(form.id)}
                    revision.generated_by = result.model
                    revision.change_summary = f"{form.code} 양식의 작성예시 생성"
                    db.flush()
            except LLMError as exc:
                errors.append(str(exc))
                progress["failed"] += 1
                log(f"실패: {form.title} — {exc}", "error")
            except Exception as exc:  # 저장 오류(번호 발급 등)는 그 건만 실패로 둔다
                detail = getattr(exc, "detail", None)
                message = detail.get("message") if isinstance(detail, dict) else str(exc)
                errors.append(message)
                progress["failed"] += 1
                log(f"실패: {form.title} — {message}", "error")
            else:
                progress["done"] += 1
                progress["input_tokens"] += result.input_tokens
                progress["output_tokens"] += result.output_tokens
                log(f"작성: {form.title} 작성예시")
            run.progress = dict(progress)
            db.commit()

    run.finished_at = datetime.now(UTC)
    if tasks and progress["done"] == 0:
        run.status, run.error = "failed", errors[0] if errors else "작성예시를 만들지 못했습니다."
    else:
        run.status = "succeeded"
    db.commit()
