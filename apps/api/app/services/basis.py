"""체계의 근거: 어느 원문의 어느 요건을 이 체계에 적용하는가.

확정된 원문만 근거로 삼을 수 있다. 적용하지 않는 요건은 사유와 함께 제외하고,
그 결과(적용요건)를 사람이 승인해야 문서 생성으로 넘어갈 수 있다.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import api_error, not_found
from app.models import (
    GenerationPlan,
    PlanSource,
    ProcessSystem,
    Requirement,
    RequirementExclusion,
    SourceClause,
    SourceDocument,
    SystemBasis,
)
from app.services import audit

# 문서가 이미 만들어졌거나 만들어지는 중인 설계안
LIVE_PLAN_STATUSES = ("designing", "proposed", "writing", "partial", "done")


def get_basis(db: Session, system_id: uuid.UUID, source_id: uuid.UUID) -> SystemBasis:
    basis = db.get(SystemBasis, {"system_id": system_id, "source_id": source_id})
    if basis is None:
        raise not_found("근거 원문")
    return basis


def list_basis(
    db: Session, system_id: uuid.UUID
) -> list[tuple[SystemBasis, SourceDocument, int, int]]:
    """(근거, 원문, 확정 요건 수, 제외한 요건 수)"""
    rows = db.execute(
        select(SystemBasis, SourceDocument)
        .join(SourceDocument, SourceDocument.id == SystemBasis.source_id)
        .where(SystemBasis.system_id == system_id)
        .order_by(SystemBasis.created_at)
    ).all()
    result = []
    for basis, source in rows:
        total = db.scalar(
            select(func.count())
            .select_from(Requirement)
            .where(Requirement.source_id == source.id, Requirement.status == "confirmed")
        )
        excluded = db.scalar(
            select(func.count())
            .select_from(RequirementExclusion)
            .join(Requirement, Requirement.id == RequirementExclusion.requirement_id)
            .where(RequirementExclusion.system_id == system_id, Requirement.source_id == source.id)
        )
        result.append((basis, source, total or 0, excluded or 0))
    return result


def attach(
    db: Session, *, system: ProcessSystem, source_id: uuid.UUID, actor_id: uuid.UUID
) -> SystemBasis:
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise not_found("원문")
    if source.status != "confirmed":
        raise api_error(
            409, "source_not_confirmed", "요건을 확정한 원문만 근거로 삼을 수 있습니다."
        )
    if db.get(SystemBasis, {"system_id": system.id, "source_id": source_id}) is not None:
        raise api_error(409, "already_attached", "이미 이 체계의 근거인 원문입니다.")

    basis = SystemBasis(
        system_id=system.id, source_id=source_id, tenant_id=system.tenant_id, created_by=actor_id
    )
    db.add(basis)
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="basis.attach",
        entity_type="system",
        entity_id=system.id,
        data={"system": system.slug, "source": source.code, "title": source.title},
    )
    return basis


def sources_in_live_plans(db: Session, system_id: uuid.UUID) -> set[uuid.UUID]:
    """이 체계에서 이미 설계안(또는 그 설계안으로 만든 문서)의 근거가 된 원문."""
    return set(
        db.scalars(
            select(PlanSource.source_id)
            .join(GenerationPlan, GenerationPlan.id == PlanSource.plan_id)
            .where(
                GenerationPlan.system_id == system_id,
                GenerationPlan.status.in_(LIVE_PLAN_STATUSES),
            )
        )
    )


def detach(db: Session, *, system: ProcessSystem, basis: SystemBasis, actor_id: uuid.UUID) -> None:
    if basis.approved_at is not None:
        raise api_error(
            409, "basis_approved", "승인된 근거는 뺄 수 없습니다. 먼저 승인을 취소하세요."
        )
    for exclusion in db.scalars(
        select(RequirementExclusion)
        .join(Requirement, Requirement.id == RequirementExclusion.requirement_id)
        .where(
            RequirementExclusion.system_id == system.id, Requirement.source_id == basis.source_id
        )
    ):
        db.delete(exclusion)
    db.delete(basis)
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="basis.detach",
        entity_type="system",
        entity_id=system.id,
        data={"system": system.slug, "source_id": str(basis.source_id)},
    )


def requirements_with_exclusions(
    db: Session, system_id: uuid.UUID, source_id: uuid.UUID
) -> list[tuple[Requirement, SourceClause, RequirementExclusion | None]]:
    """확정된 요건 전부와, 이 체계에서 제외했는지."""
    return list(
        db.execute(
            select(Requirement, SourceClause, RequirementExclusion)
            .join(SourceClause, SourceClause.id == Requirement.clause_id)
            .outerjoin(
                RequirementExclusion,
                (RequirementExclusion.requirement_id == Requirement.id)
                & (RequirementExclusion.system_id == system_id),
            )
            .where(Requirement.source_id == source_id, Requirement.status == "confirmed")
            .order_by(SourceClause.position, Requirement.position)
        ).all()
    )


def applicable_requirements(
    db: Session, system_id: uuid.UUID, source_id: uuid.UUID
) -> list[tuple[Requirement, SourceClause]]:
    """이 체계에 적용하는 요건(확정됐고 제외하지 않은 것)."""
    return [
        (requirement, clause)
        for requirement, clause, exclusion in requirements_with_exclusions(db, system_id, source_id)
        if exclusion is None
    ]


def set_exclusion(
    db: Session,
    *,
    system: ProcessSystem,
    basis: SystemBasis,
    requirement_id: uuid.UUID,
    excluded: bool,
    reason: str,
    actor_id: uuid.UUID,
) -> None:
    if basis.approved_at is not None:
        raise api_error(
            409, "basis_approved", "승인된 적용요건은 바꿀 수 없습니다. 먼저 승인을 취소하세요."
        )
    requirement = db.get(Requirement, requirement_id)
    if (
        requirement is None
        or requirement.source_id != basis.source_id
        or requirement.status != "confirmed"
    ):
        raise not_found("요건")

    key = {"system_id": system.id, "requirement_id": requirement_id}
    existing = db.get(RequirementExclusion, key)
    if not excluded:
        if existing is not None:
            db.delete(existing)
            db.flush()
        return
    if not reason.strip():
        raise api_error(
            422, "reason_required", "적용하지 않는 사유를 입력하세요. 심사에서 설명해야 합니다."
        )
    if existing is None:
        db.add(
            RequirementExclusion(
                **key, tenant_id=system.tenant_id, reason=reason.strip(), excluded_by=actor_id
            )
        )
    else:
        existing.reason = reason.strip()
        existing.excluded_by = actor_id
    db.flush()


def approve(
    db: Session, *, system: ProcessSystem, basis: SystemBasis, actor_id: uuid.UUID
) -> SystemBasis:
    if basis.approved_at is not None:
        raise api_error(409, "basis_approved", "이미 승인된 적용요건입니다.")
    applicable = applicable_requirements(db, system.id, basis.source_id)
    if not applicable:
        raise api_error(409, "nothing_applicable", "적용할 요건이 하나도 없습니다.")
    basis.approved_by = actor_id
    basis.approved_at = datetime.now(UTC)
    db.flush()
    excluded = db.scalar(
        select(func.count())
        .select_from(RequirementExclusion)
        .join(Requirement, Requirement.id == RequirementExclusion.requirement_id)
        .where(
            RequirementExclusion.system_id == system.id, Requirement.source_id == basis.source_id
        )
    )
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="basis.approve",
        entity_type="system",
        entity_id=system.id,
        data={
            "system": system.slug,
            "source_id": str(basis.source_id),
            "applicable": len(applicable),
            "excluded": excluded or 0,
        },
    )
    return basis


def reopen(
    db: Session, *, system: ProcessSystem, basis: SystemBasis, actor_id: uuid.UUID
) -> SystemBasis:
    """승인을 취소한다. 이 적용요건으로 문서를 설계·생성한 뒤에는 할 수 없다."""
    if basis.approved_at is None:
        raise api_error(409, "not_approved", "승인되지 않은 적용요건입니다.")
    if basis.source_id in sources_in_live_plans(db, system.id):
        raise api_error(
            409,
            "plan_exists",
            "이 적용요건으로 만든 설계안이나 문서가 있어 승인을 취소할 수 없습니다.",
        )
    basis.approved_by = None
    basis.approved_at = None
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="basis.reopen",
        entity_type="system",
        entity_id=system.id,
        data={"system": system.slug, "source_id": str(basis.source_id)},
    )
    return basis
