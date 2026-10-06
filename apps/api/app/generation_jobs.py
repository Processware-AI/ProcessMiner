"""문서 구조 설계와 문서 작성 작업. 작업자(app.worker)가 부른다.

모델 호출은 app.pipelines.planning 이 하고, 여기서는 DB 에서 재료를 모으고 결과를 저장한다.
문서는 상위부터 단계별로 쓴다(정책 → 절차 → 지침 → 템플릿). 상위 문서가 만들어지지 않으면
그 아래는 쓰지 않는다(쓸 곳이 없는 문서에 비용을 들이지 않는다).
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import LLMError
from app.models import (
    DocTypeDef,
    DocumentRequirement,
    GenerationPlan,
    ProcessSystem,
    Requirement,
    Run,
    RunEvent,
)
from app.pipelines import planning
from app.pipelines.planning import GroundingError, PlanNode, RequirementBrief, WriteTask
from app.schemas import DocumentIn
from app.services import basis as basis_service
from app.services import documents as doc_service
from app.services import plans as plan_service

logger = logging.getLogger(__name__)

_LEVELS = ("POL", "PRO", "WI", "TMP")


def _log(db: Session, run: Run, message: str, level: str = "info") -> None:
    db.add(RunEvent(tenant_id=run.tenant_id, run_id=run.id, level=level, message=message))


def _finish(db: Session, run: Run, status: str, error: str = "") -> None:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)


def _applicable(
    db: Session, plan: GenerationPlan
) -> tuple[dict[str, RequirementBrief], dict[str, Requirement]]:
    """설계안의 모든 원문에서 적용요건을 모은다. 코드에는 원문 약칭을 붙여 서로 구분한다."""
    briefs: dict[str, RequirementBrief] = {}
    rows: dict[str, Requirement] = {}
    for source in plan_service.plan_sources(db, plan.id):
        for requirement, clause in basis_service.applicable_requirements(
            db, plan.system_id, source.id
        ):
            code = planning.qualified_code(source.code, requirement.code)
            briefs[code] = RequirementBrief(
                code=code,
                clause_number=clause.number,
                clause_title=clause.title,
                obligation=requirement.obligation,
                category=requirement.category,
                summary=requirement.summary,
                quote=requirement.quote,
                applicability=requirement.applicability,
                evidence=requirement.evidence,
                standard=source.code,
                standard_title=source.title,
            )
            rows[code] = requirement
    return briefs, rows


# ── 구조 설계 ────────────────────────────────────────────────────────────────


def run_design(db: Session, run: Run) -> None:
    plan = db.get(GenerationPlan, run.plan_id)
    briefs, _ = _applicable(db, plan)
    standards = list(dict.fromkeys(brief.standard for brief in briefs.values()))
    _log(db, run, f"{', '.join(standards)} 적용요건 {len(briefs)}건으로 문서 구조를 설계합니다")
    db.commit()

    try:
        result = planning.design(list(briefs.values()))
    except LLMError as exc:
        plan.status = "failed"
        _finish(db, run, "failed", str(exc))
        db.commit()
        return

    nodes = planning.flatten(result.structure)
    if not nodes:
        plan.status = "failed"
        _finish(db, run, "failed", "모델이 문서 구조를 내놓지 못했습니다. 다시 설계하세요.")
        db.commit()
        return

    plan.structure = result.structure
    plan.uncovered = result.uncovered
    plan.model = result.model
    plan.status = "proposed"
    run.progress = {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens}
    counts = {t: sum(n.doc_type == t for n in nodes) for t in _LEVELS}
    shared = sum(len(planning.by_standard(n.requirements)) > 1 for n in nodes)
    _log(
        db,
        run,
        f"설계 완료: 정책 {counts['POL']}, 절차 {counts['PRO']}, 지침 {counts['WI']}, "
        f"템플릿 {counts['TMP']}",
    )
    if len(standards) > 1:
        _log(db, run, f"여러 표준의 요건을 함께 이행하는 문서 {shared}건")
    if result.uncovered:
        _log(db, run, f"배정되지 않은 요건 {len(result.uncovered)}건", level="error")
    _finish(db, run, "succeeded")
    db.commit()


# ── 문서 작성 ────────────────────────────────────────────────────────────────


def _task(
    node: PlanNode,
    nodes: list[PlanNode],
    by_path: dict[str, PlanNode],
    briefs: dict[str, RequirementBrief],
    schemas: dict[str, list[dict[str, Any]]],
) -> WriteTask:
    if node.doc_type == "TMP":
        # 템플릿은 상위 지침의 요건이 요구하는 기록을 담는다.
        assigned: list[str] = []
        allowed = by_path[node.parent].requirements
    else:
        assigned = node.requirements
        # 상위 문서는 하위 문서가 이행하는 요건까지 근거로 댈 수 있다.
        allowed = [
            code
            for other in nodes
            if other.path == node.path or other.path.startswith(node.path + ".")
            for code in other.requirements
        ]
    ancestors: list[str] = []
    parent = node.parent
    while parent:
        ancestors.insert(0, by_path[parent].title)
        parent = by_path[parent].parent
    return WriteTask(
        node=node,
        section_schema=schemas[node.doc_type],
        assigned=[briefs[c] for c in assigned if c in briefs],
        allowed=[briefs[c] for c in dict.fromkeys(allowed) if c in briefs],
        ancestors=ancestors,
        children=[n.title for n in nodes if n.parent == node.path],
    )


def _persist(
    db: Session,
    *,
    plan: GenerationPlan,
    system: ProcessSystem,
    standards: list[str],
    node: PlanNode,
    parent_document_id: str | None,
    written: planning.WriteResult,
    requirement_rows: dict[str, Requirement],
) -> str:
    """쓴 본문을 초안 문서로 저장하고 섹션별 근거 링크를 남긴다. 문서 id 를 돌려준다."""
    author_id = plan.accepted_by or plan.created_by
    document = doc_service.create_document(
        db,
        system=system,
        payload=DocumentIn(
            doc_type=node.doc_type,
            title=node.title[:300],
            scope_code=plan.scope_code if node.doc_type == "POL" else None,
            parent_id=parent_document_id,
        ),
        actor_id=author_id,
    )
    revision = doc_service.open_revision(db, document.id)
    revision.sections = written.sections
    # 섹션별 근거는 document_requirement 에만 둔다(한곳에서만 관리한다).
    revision.structured = {"plan_id": str(plan.id)}
    revision.generated_by = written.model
    cited = planning.by_standard([c for codes in written.citations.values() for c in codes])
    basis = [s for s in standards if s in cited] or standards
    revision.change_summary = f"{', '.join(basis)} 적용요건에서 생성"
    db.flush()
    for section_key, codes in written.citations.items():
        for code in codes:
            db.add(
                DocumentRequirement(
                    revision_id=revision.id,
                    section_key=section_key,
                    requirement_id=requirement_rows[code].id,
                    tenant_id=plan.tenant_id,
                    document_id=document.id,
                )
            )
    db.flush()
    return str(document.id)


def run_write(db: Session, run: Run) -> None:
    plan = db.get(GenerationPlan, run.plan_id)
    system = db.get(ProcessSystem, plan.system_id)
    standards = [source.code for source in plan_service.plan_sources(db, plan.id)]
    briefs, requirement_rows = _applicable(db, plan)
    schemas = {row.code: row.sections for row in db.scalars(select(DocTypeDef))}
    nodes = planning.flatten(plan.structure)
    by_path = {node.path: node for node in nodes}
    requested = set(run.progress.get("paths", []))
    results: dict[str, Any] = dict(plan.results)

    def is_done(path: str | None) -> bool:
        return path is None or results.get(path, {}).get("status") == "done"

    targets = [n for n in nodes if n.path in requested and not is_done(n.path)]
    progress = {
        "paths": sorted(requested),
        "done": 0,
        "failed": 0,
        "total": len(targets),
        "input_tokens": 0,
        "output_tokens": 0,
    }
    run.progress = dict(progress)
    _log(db, run, f"문서 {len(targets)}건을 작성합니다")
    db.commit()

    def save_state() -> None:
        plan.results = dict(results)
        run.progress = dict(progress)
        db.commit()

    with ThreadPoolExecutor(max_workers=max(1, get_settings().llm_concurrency)) as pool:
        for doc_type in _LEVELS:
            level = [n for n in targets if n.doc_type == doc_type]
            ready = [n for n in level if is_done(n.parent)]
            for node in level:
                if node not in ready:
                    results[node.path] = {
                        "status": "failed",
                        "error": "상위 문서가 만들어지지 않아 건너뛰었습니다.",
                    }
                    progress["failed"] += 1
            if len(ready) < len(level):
                save_state()

            futures = {
                pool.submit(planning.write, _task(n, nodes, by_path, briefs, schemas)): n
                for n in ready
            }
            for future in as_completed(futures):
                node = futures[future]
                try:
                    written = future.result()
                    with db.begin_nested():
                        document_id = _persist(
                            db,
                            plan=plan,
                            system=system,
                            standards=standards,
                            node=node,
                            parent_document_id=(
                                results[node.parent]["document_id"] if node.parent else None
                            ),
                            written=written,
                            requirement_rows=requirement_rows,
                        )
                except (LLMError, GroundingError) as exc:
                    results[node.path] = {"status": "failed", "error": str(exc)}
                    progress["failed"] += 1
                    _log(db, run, f"실패: {node.title} — {exc}", level="error")
                except Exception as exc:
                    logger.exception("문서 저장 실패: %s", node.title)
                    detail = getattr(exc, "detail", None)
                    message = detail.get("message") if isinstance(detail, dict) else None
                    results[node.path] = {
                        "status": "failed",
                        "error": message or "문서를 저장하지 못했습니다.",
                    }
                    progress["failed"] += 1
                    _log(db, run, f"실패: {node.title} — 저장 오류", level="error")
                else:
                    results[node.path] = {"status": "done", "document_id": document_id}
                    progress["done"] += 1
                    progress["input_tokens"] += written.input_tokens
                    progress["output_tokens"] += written.output_tokens
                    _log(db, run, f"작성: [{node.doc_type}] {node.title}")
                # 문서 하나가 끝날 때마다 반영해 화면에서 진행 상황이 보이게 한다.
                save_state()

    plan.status = "done" if all(is_done(n.path) for n in nodes) else "partial"
    if targets and progress["done"] == 0:
        first_error = next(
            (r["error"] for r in results.values() if r.get("status") == "failed"), ""
        )
        _finish(db, run, "failed", first_error or "문서를 하나도 만들지 못했습니다.")
    else:
        _finish(db, run, "succeeded")
    save_state()


def recover_after_failure(db: Session, run: Run) -> None:
    """작업이 예상하지 못한 오류로 끝났을 때 설계안이 '진행 중' 으로 남지 않게 한다."""
    plan = db.get(GenerationPlan, run.plan_id) if run.plan_id else None
    if plan is None:
        return
    if plan.status == "designing":
        plan.status = "failed"
    elif plan.status == "writing":
        plan.status = "partial"
