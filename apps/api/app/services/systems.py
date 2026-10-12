"""체계 관리: 빈 체계 삭제.

체계를 지우면 근거·설계안·역할 부여도 함께 지워진다(외래 키 CASCADE).
문서·하위 체계·기록이 남아 있으면 지우지 않는다. 승인된 적 있는 문서는 폐지해도 이력으로
남으므로, 그런 체계는 지울 수 없다.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import api_error
from app.models import (
    Artifact,
    DocSequence,
    Document,
    GenerationPlan,
    ProcessRecord,
    ProcessSystem,
    Run,
)
from app.services import audit
from app.services.plans import ACTIVE_RUN_STATUSES


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def delete_blockers(db: Session, system: ProcessSystem) -> list[str]:
    """체계를 지울 수 없는 이유(사람이 읽는 문장). 비어 있으면 지울 수 있다."""
    blockers = []
    children = _count(db, ProcessSystem, ProcessSystem.parent_system_id == system.id)
    if children:
        blockers.append(f"하위 체계 {children}개")
    active = _count(db, Document, Document.system_id == system.id, Document.retired_at.is_(None))
    if active:
        blockers.append(f"문서 {active}건")
    retired = _count(
        db, Document, Document.system_id == system.id, Document.retired_at.is_not(None)
    )
    if retired:
        blockers.append(f"폐지한 문서 {retired}건(승인 이력이 남아 있어 지울 수 없음)")
    records = _count(db, ProcessRecord, ProcessRecord.system_id == system.id)
    if records:
        blockers.append(f"기록 {records}건")
    artifacts = _count(db, Artifact, Artifact.system_id == system.id)
    if artifacts:
        blockers.append(f"올린 산출물 {artifacts}건")
    plan_ids = select(GenerationPlan.id).where(GenerationPlan.system_id == system.id)
    running = _count(
        db,
        Run,
        Run.status.in_(ACTIVE_RUN_STATUSES),
        Run.plan_id.in_(plan_ids) | (Run.progress["system_id"].astext == str(system.id)),
    )
    if running:
        blockers.append("진행 중인 작업")
    return blockers


def delete(db: Session, *, system: ProcessSystem, actor_id: uuid.UUID) -> None:
    blockers = delete_blockers(db, system)
    if blockers:
        raise api_error(
            409,
            "system_not_empty",
            f"체계가 비어 있지 않아 삭제할 수 없습니다: {', '.join(blockers)}. "
            "문서는 다른 체계로 옮기거나 삭제하세요.",
        )
    # 작업 기록(run·run_event)은 지울 수 없고 비용 기록으로도 남겨야 하므로,
    # 설계안과의 연결만 끊는다.
    db.execute(
        update(Run)
        .where(
            Run.plan_id.in_(select(GenerationPlan.id).where(GenerationPlan.system_id == system.id))
        )
        .values(plan_id=None)
    )
    if system.parent_system_id is None:
        # 기준선 체계의 번호 카운터. 하위 체계가 없으므로 이 계보를 쓰는 체계가 더 없다.
        for sequence in db.scalars(
            select(DocSequence).where(DocSequence.root_system_id == system.id)
        ):
            db.delete(sequence)
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="system.delete",
        entity_type="system",
        entity_id=system.id,
        data={"slug": system.slug, "name": system.name},
    )
    db.delete(system)
    db.flush()
