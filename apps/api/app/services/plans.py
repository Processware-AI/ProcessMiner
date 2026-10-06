"""문서 생성 계획: 구조 설계를 요청하고, 사람이 받아들인 설계안으로 문서를 쓴다.

설계와 작성 자체는 작업자가 한다(app.worker). 여기는 무엇을 언제 시작할 수 있는지의 규칙이다.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import api_error, not_found
from app.models import (
    GenerationPlan,
    PlanSource,
    ProcessSystem,
    Run,
    ScopeCode,
    SourceDocument,
    SystemBasis,
)
from app.pipelines import planning
from app.services import audit
from app.services.basis import sources_in_live_plans

ACTIVE_RUN_STATUSES = ("queued", "running")


def get_plan(db: Session, plan_id: uuid.UUID) -> GenerationPlan:
    plan = db.get(GenerationPlan, plan_id)
    if plan is None:
        raise not_found("설계안")
    return plan


def list_plans(db: Session, system_id: uuid.UUID) -> list[GenerationPlan]:
    """버린 것을 뺀 설계안. 최근 것이 먼저."""
    return list(
        db.scalars(
            select(GenerationPlan)
            .where(GenerationPlan.system_id == system_id, GenerationPlan.status != "discarded")
            .order_by(GenerationPlan.created_at.desc())
        )
    )


def plan_sources(db: Session, plan_id: uuid.UUID) -> list[SourceDocument]:
    """설계안이 근거로 삼는 원문. 체계의 근거로 추가한 순서."""
    return list(
        db.scalars(
            select(SourceDocument)
            .join(PlanSource, PlanSource.source_id == SourceDocument.id)
            .join(GenerationPlan, GenerationPlan.id == PlanSource.plan_id)
            .join(
                SystemBasis,
                (SystemBasis.system_id == GenerationPlan.system_id)
                & (SystemBasis.source_id == SourceDocument.id),
            )
            .where(PlanSource.plan_id == plan_id)
            .order_by(SystemBasis.created_at, SourceDocument.code)
        )
    )


def latest_run(db: Session, plan_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run).where(Run.plan_id == plan_id).order_by(Run.created_at.desc()).limit(1)
    )


def has_active_run(db: Session, plan_id: uuid.UUID) -> bool:
    run = latest_run(db, plan_id)
    return run is not None and run.status in ACTIVE_RUN_STATUSES


def start_design(
    db: Session,
    *,
    system: ProcessSystem,
    source_ids: list[uuid.UUID],
    scope_code: str,
    actor_id: uuid.UUID,
) -> GenerationPlan:
    """원문 하나 또는 여럿의 적용요건으로 문서 구조를 설계한다.

    여럿을 고르면 표준별로 문서를 따로 두지 않고 하나의 체계로 통합해 설계한다.
    """
    source_ids = list(dict.fromkeys(source_ids))
    sources: list[SourceDocument] = []
    for source_id in source_ids:
        basis = db.get(SystemBasis, {"system_id": system.id, "source_id": source_id})
        if basis is None:
            raise not_found("근거 원문")
        if basis.approved_at is None:
            raise api_error(
                409, "basis_not_approved", "적용요건을 승인한 뒤에 문서 구조를 설계할 수 있습니다."
            )
        sources.append(db.get(SourceDocument, source_id))
    if db.scalar(select(ScopeCode.id).where(ScopeCode.code == scope_code)) is None:
        raise api_error(422, "unknown_scope", f"등록되지 않은 영역코드입니다: {scope_code}")
    codes = [source.code for source in sources]
    if len(set(codes)) < len(codes):
        # 요건 코드를 "약칭 번호" 로 구분하므로 약칭이 같으면 어느 원문의 요건인지 알 수 없다.
        raise api_error(
            409,
            "duplicate_source_code",
            "약칭이 같은 원문을 함께 설계할 수 없습니다. 원문의 약칭을 서로 다르게 하세요.",
        )
    taken = sources_in_live_plans(db, system.id) & set(source_ids)
    if taken:
        names = ", ".join(source.code for source in sources if source.id in taken)
        raise api_error(
            409,
            "plan_exists",
            f"이미 설계안이 있는 원문입니다({names}). 새로 설계하려면 먼저 그 설계안을 버리세요.",
        )

    plan = GenerationPlan(
        tenant_id=system.tenant_id,
        system_id=system.id,
        scope_code=scope_code,
        status="designing",
        created_by=actor_id,
    )
    db.add(plan)
    db.flush()
    db.add_all(
        PlanSource(plan_id=plan.id, source_id=source.id, tenant_id=system.tenant_id)
        for source in sources
    )
    db.add(
        Run(
            tenant_id=system.tenant_id,
            kind="design_system",
            status="queued",
            plan_id=plan.id,
            started_by=actor_id,
        )
    )
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="plan.design",
        entity_type="plan",
        entity_id=plan.id,
        data={"system": system.slug, "scope_code": scope_code, "sources": codes},
    )
    return plan


def pending_paths(plan: GenerationPlan, under: list[str] | None = None) -> list[str]:
    """아직 만들어지지 않은 문서의 경로. under 가 있으면 그 정책들 아래만."""
    done = {path for path, result in plan.results.items() if result.get("status") == "done"}
    paths = []
    for node in planning.flatten(plan.structure):
        if node.path in done:
            continue
        if under and not any(node.path == p or node.path.startswith(p + ".") for p in under):
            continue
        paths.append(node.path)
    return paths


def start_writing(
    db: Session,
    *,
    system: ProcessSystem,
    plan: GenerationPlan,
    policies: list[str] | None,
    actor_id: uuid.UUID,
) -> Run:
    """설계안을 받아들이고 문서를 쓴다. policies 로 일부 정책만 고를 수 있다."""
    if plan.status not in ("proposed", "partial"):
        raise api_error(409, "invalid_status", "지금은 문서를 생성할 수 없는 상태입니다.")
    if has_active_run(db, plan.id):
        raise api_error(409, "run_in_progress", "이미 작업이 진행 중입니다.")
    if plan.uncovered:
        raise api_error(
            409,
            "uncovered_requirements",
            f"어느 문서에도 배정되지 않은 적용요건이 {len(plan.uncovered)}건 있습니다. "
            "다시 설계하세요.",
        )
    top_level = {n.path for n in planning.flatten(plan.structure) if n.doc_type == "POL"}
    if policies is not None and not set(policies) <= top_level:
        raise api_error(422, "unknown_policy", "설계안에 없는 정책입니다.")
    paths = pending_paths(plan, policies)
    if not paths:
        raise api_error(409, "nothing_to_write", "생성할 문서가 남아 있지 않습니다.")

    if plan.accepted_at is None:
        plan.accepted_by = actor_id
        plan.accepted_at = datetime.now(UTC)
    plan.status = "writing"
    run = Run(
        tenant_id=system.tenant_id,
        kind="write_documents",
        status="queued",
        plan_id=plan.id,
        progress={"paths": paths},
        started_by=actor_id,
    )
    db.add(run)
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="plan.write",
        entity_type="plan",
        entity_id=plan.id,
        data={"system": system.slug, "documents": len(paths)},
    )
    return run


def discard(
    db: Session, *, system: ProcessSystem, plan: GenerationPlan, actor_id: uuid.UUID
) -> None:
    """설계안을 버린다. 이 설계안으로 문서를 하나라도 만들었으면 버릴 수 없다."""
    if has_active_run(db, plan.id):
        raise api_error(409, "run_in_progress", "작업이 끝난 뒤에 버릴 수 있습니다.")
    if any(result.get("status") == "done" for result in plan.results.values()):
        raise api_error(409, "documents_exist", "이 설계안으로 만든 문서가 있어 버릴 수 없습니다.")
    plan.status = "discarded"
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="plan.discard",
        entity_type="plan",
        entity_id=plan.id,
        data={"system": system.slug},
    )
