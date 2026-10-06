"""체계의 근거(적용요건)와, 요건에서 문서를 생성하는 설계안."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.sources import _requirement_out, _run_out
from app.db import CommitRoute
from app.deps import TenantContext, tenant_context
from app.errors import not_found
from app.models import (
    AppUser,
    Document,
    DocumentRequirement,
    GenerationPlan,
    ProcessSystem,
    Requirement,
    SourceClause,
    SourceDocument,
)
from app.pipelines import planning
from app.schemas import (
    BasisAttachIn,
    BasisItem,
    BasisOut,
    BasisRequirementOut,
    CoverageOut,
    DocumentRef,
    ExclusionIn,
    PlanEditIn,
    PlanNodeOut,
    PlanOut,
    PlanStartIn,
    PlanWriteIn,
    RevisionRequirementOut,
    SourceRef,
    UserRef,
)
from app.services import audit as audit_svc
from app.services import basis as basis_svc
from app.services import coverage as coverage_svc
from app.services import documents as doc_svc
from app.services import plans as plan_svc

router = APIRouter(prefix="/api", tags=["build"], route_class=CommitRoute)

_SYSTEM = "/t/{tenant_slug}/systems/{system_slug}"


def _source_ref(source: SourceDocument) -> SourceRef:
    return SourceRef(id=source.id, code=source.code, title=source.title, edition=source.edition)


# ── 근거 ─────────────────────────────────────────────────────────────────────


def _basis_out(ctx: TenantContext, system: ProcessSystem) -> BasisOut:
    db = ctx.db
    rows = basis_svc.list_basis(db, system.id)
    approvers = {
        u.id: UserRef(id=u.id, name=u.name)
        for u in db.scalars(
            select(AppUser).where(AppUser.id.in_({b.approved_by for b, _, _, _ in rows}))
        )
    }
    in_plan = basis_svc.sources_in_live_plans(db, system.id)
    can_manage = ctx.can("basis.manage", system.id)

    items = []
    for basis, source, total, excluded in rows:
        actions: list[str] = []
        approved = basis.approved_at is not None
        live = source.id in in_plan
        if not approved:
            if can_manage:
                actions += ["review", "detach"]
            if ctx.can("basis.approve", system.id):
                actions.append("approve")
        else:
            if ctx.can("basis.approve", system.id) and not live:
                actions.append("reopen")
            if ctx.can("plan.manage", system.id) and not live:
                actions.append("design")
        items.append(
            BasisItem(
                source=_source_ref(source),
                total=total,
                excluded=excluded,
                approved_at=basis.approved_at,
                approved_by=approvers.get(basis.approved_by),
                actions=actions,
            )
        )

    attached = {source.id for _, source, _, _ in rows}
    available = [
        _source_ref(source)
        for source in db.scalars(
            select(SourceDocument)
            .where(SourceDocument.status == "confirmed")
            .order_by(SourceDocument.created_at)
        )
        if source.id not in attached
    ]
    return BasisOut(items=items, available=available, actions=["attach"] if can_manage else [])


@router.get(f"{_SYSTEM}/basis", response_model=BasisOut)
def get_basis(system_slug: str, ctx: TenantContext = Depends(tenant_context)) -> BasisOut:
    system = ctx.system_by_slug(system_slug)
    ctx.require("system.read", system.id)
    return _basis_out(ctx, system)


@router.post(f"{_SYSTEM}/basis", response_model=BasisOut, status_code=201)
def attach_source(
    system_slug: str, payload: BasisAttachIn, ctx: TenantContext = Depends(tenant_context)
) -> BasisOut:
    system = ctx.system_by_slug(system_slug)
    ctx.require("basis.manage", system.id)
    basis_svc.attach(ctx.db, system=system, source_id=payload.source_id, actor_id=ctx.user.id)
    return _basis_out(ctx, system)


@router.delete(f"{_SYSTEM}/basis/{{source_id}}", response_model=BasisOut)
def detach_source(
    system_slug: str, source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> BasisOut:
    system = ctx.system_by_slug(system_slug)
    ctx.require("basis.manage", system.id)
    basis = basis_svc.get_basis(ctx.db, system.id, source_id)
    basis_svc.detach(ctx.db, system=system, basis=basis, actor_id=ctx.user.id)
    return _basis_out(ctx, system)


@router.get(f"{_SYSTEM}/basis/{{source_id}}/requirements", response_model=list[BasisRequirementOut])
def list_basis_requirements(
    system_slug: str, source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> list[BasisRequirementOut]:
    system = ctx.system_by_slug(system_slug)
    ctx.require("system.read", system.id)
    basis_svc.get_basis(ctx.db, system.id, source_id)
    return [
        BasisRequirementOut(
            **_requirement_out(requirement, clause.number).model_dump(),
            excluded=exclusion is not None,
            reason=exclusion.reason if exclusion else "",
        )
        for requirement, clause, exclusion in basis_svc.requirements_with_exclusions(
            ctx.db, system.id, source_id
        )
    ]


@router.put(f"{_SYSTEM}/basis/{{source_id}}/requirements/{{requirement_id}}", status_code=204)
def set_requirement_exclusion(
    system_slug: str,
    source_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: ExclusionIn,
    ctx: TenantContext = Depends(tenant_context),
) -> None:
    system = ctx.system_by_slug(system_slug)
    ctx.require("basis.manage", system.id)
    basis_svc.set_exclusion(
        ctx.db,
        system=system,
        basis=basis_svc.get_basis(ctx.db, system.id, source_id),
        requirement_id=requirement_id,
        excluded=payload.excluded,
        reason=payload.reason,
        actor_id=ctx.user.id,
    )


@router.post(f"{_SYSTEM}/basis/{{source_id}}/approve", response_model=BasisOut)
def approve_basis(
    system_slug: str, source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> BasisOut:
    system = ctx.system_by_slug(system_slug)
    ctx.require("basis.approve", system.id)
    basis = basis_svc.get_basis(ctx.db, system.id, source_id)
    basis_svc.approve(ctx.db, system=system, basis=basis, actor_id=ctx.user.id)
    return _basis_out(ctx, system)


@router.post(f"{_SYSTEM}/basis/{{source_id}}/reopen", response_model=BasisOut)
def reopen_basis(
    system_slug: str, source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> BasisOut:
    system = ctx.system_by_slug(system_slug)
    ctx.require("basis.approve", system.id)
    basis = basis_svc.get_basis(ctx.db, system.id, source_id)
    basis_svc.reopen(ctx.db, system=system, basis=basis, actor_id=ctx.user.id)
    return _basis_out(ctx, system)


# ── 설계안 ───────────────────────────────────────────────────────────────────


def _plan_out(ctx: TenantContext, system: ProcessSystem, plan: GenerationPlan) -> PlanOut:
    db = ctx.db
    sources = plan_svc.plan_sources(db, plan.id)
    run = plan_svc.latest_run(db, plan.id)
    busy = run is not None and run.status in plan_svc.ACTIVE_RUN_STATUSES

    flat = planning.flatten(plan.structure)
    linked = (
        {
            doc.id: DocumentRef(id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type)
            for doc in db.scalars(
                select(Document).where(
                    Document.id.in_({uuid.UUID(x) for n in flat for x in (n.target, n.anchor) if x})
                )
            )
        }
        if any(n.target or n.anchor for n in flat)
        else {}
    )
    nodes = []
    for node in flat:
        result = plan.results.get(node.path, {})
        nodes.append(
            PlanNodeOut(
                path=node.path,
                doc_type=node.doc_type,
                title=node.title,
                purpose=node.purpose,
                parent=node.parent,
                requirements=node.requirements,
                by_standard=planning.by_standard(node.requirements),
                integration_note=node.note,
                target=linked.get(uuid.UUID(node.target)) if node.target else None,
                anchor=linked.get(uuid.UUID(node.anchor)) if node.anchor else None,
                status=result.get("status", "pending"),
                document_id=result.get("document_id"),
                error=result.get("error", ""),
            )
        )

    actions: list[str] = []
    if ctx.can("plan.manage", system.id) and not busy:
        pending = any(n.status != "done" for n in nodes)
        if plan.status in ("proposed", "partial") and pending and not plan.uncovered:
            actions.append("write")
        if plan.status == "proposed" and plan.mode == "new":
            actions.append("edit")
        if plan.status in ("proposed", "failed") or (
            plan.status == "partial" and not any(n.status == "done" for n in nodes)
        ):
            actions.append("discard")

    applicable = {
        source.code: len(basis_svc.applicable_requirements(db, system.id, source.id))
        for source in sources
    }
    return PlanOut(
        id=plan.id,
        status=plan.status,
        mode=plan.mode,
        scope_code=plan.scope_code,
        sources=[_source_ref(source) for source in sources],
        model=plan.model,
        applicable_count=sum(applicable.values()),
        applicable_by_standard=applicable,
        uncovered=plan.uncovered,
        nodes=nodes,
        created_at=plan.created_at,
        accepted_at=plan.accepted_at,
        run=_run_out(db, run),
        actions=actions,
    )


def _plan_for(ctx: TenantContext, system: ProcessSystem, plan_id: uuid.UUID) -> GenerationPlan:
    plan = plan_svc.get_plan(ctx.db, plan_id)
    if plan.system_id != system.id:
        raise not_found("설계안")
    return plan


@router.get(f"{_SYSTEM}/plans", response_model=list[PlanOut])
def list_plans(system_slug: str, ctx: TenantContext = Depends(tenant_context)) -> list[PlanOut]:
    system = ctx.system_by_slug(system_slug)
    ctx.require("system.read", system.id)
    return [_plan_out(ctx, system, plan) for plan in plan_svc.list_plans(ctx.db, system.id)]


@router.post(f"{_SYSTEM}/plans", response_model=PlanOut, status_code=201)
def start_plan(
    system_slug: str, payload: PlanStartIn, ctx: TenantContext = Depends(tenant_context)
) -> PlanOut:
    """적용요건에서 문서 구조를 설계한다. 작업은 대기열에 들어간다."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("plan.manage", system.id)
    plan = plan_svc.start_design(
        ctx.db,
        system=system,
        source_ids=payload.source_ids,
        scope_code=payload.scope_code,
        actor_id=ctx.user.id,
        mode=payload.mode,
    )
    return _plan_out(ctx, system, plan)


@router.put(f"{_SYSTEM}/plans/{{plan_id}}", response_model=PlanOut)
def edit_plan(
    system_slug: str,
    plan_id: uuid.UUID,
    payload: PlanEditIn,
    ctx: TenantContext = Depends(tenant_context),
) -> PlanOut:
    """사람이 고친 설계안으로 바꾼다. 문서를 생성하기 전에만 할 수 있다."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("plan.manage", system.id)
    plan = _plan_for(ctx, system, plan_id)
    plan_svc.edit(
        ctx.db, system=system, plan=plan, structure=payload.model_dump(), actor_id=ctx.user.id
    )
    return _plan_out(ctx, system, plan)


@router.post(f"{_SYSTEM}/plans/{{plan_id}}/write", response_model=PlanOut)
def write_plan(
    system_slug: str,
    plan_id: uuid.UUID,
    payload: PlanWriteIn,
    ctx: TenantContext = Depends(tenant_context),
) -> PlanOut:
    """설계안을 받아들이고 문서를 생성한다. 문서는 초안으로 만들어져 사람의 검토를 기다린다."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("plan.manage", system.id)
    plan = _plan_for(ctx, system, plan_id)
    plan_svc.start_writing(
        ctx.db, system=system, plan=plan, policies=payload.policies, actor_id=ctx.user.id
    )
    return _plan_out(ctx, system, plan)


@router.delete(f"{_SYSTEM}/plans/{{plan_id}}", status_code=204)
def discard_plan(
    system_slug: str, plan_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> None:
    system = ctx.system_by_slug(system_slug)
    ctx.require("plan.manage", system.id)
    plan_svc.discard(
        ctx.db, system=system, plan=_plan_for(ctx, system, plan_id), actor_id=ctx.user.id
    )


# ── 표준 커버리지 ────────────────────────────────────────────────────────────


@router.get(f"{_SYSTEM}/coverage", response_model=CoverageOut)
def get_coverage(
    system_slug: str,
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: TenantContext = Depends(tenant_context),
) -> CoverageOut:
    """이 체계가 근거로 삼은 표준의 요건이 어느 문서에서 이행되는지."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    return coverage_svc.system_coverage(ctx.db, system, date_from, date_to)


@router.get(f"{_SYSTEM}/audit-pack.xlsx", response_class=Response)
def download_audit_pack(
    system_slug: str,
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: TenantContext = Depends(tenant_context),
) -> Response:
    """심사 증적 묶음: 표준별로 요건 → 이행 문서 → 기록을 한 표에 담은 XLSX."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    coverage = coverage_svc.system_coverage(ctx.db, system, date_from, date_to)
    data = coverage_svc.audit_pack_xlsx(coverage, system.name, ctx.tenant.name)
    name = f"audit-pack-{system.slug}-{datetime.now(UTC):%Y%m%d}.xlsx"
    audit_svc.record(
        ctx.db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="audit_pack.export",
        entity_type="system",
        entity_id=system.id,
        data={
            "system": system.slug,
            "date_from": str(date_from) if date_from else None,
            "date_to": str(date_to) if date_to else None,
            "sources": [s.source.code for s in coverage.sources],
        },
    )
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ── 문서의 근거 ──────────────────────────────────────────────────────────────


@router.get(
    "/t/{tenant_slug}/revisions/{revision_id}/requirements",
    response_model=list[RevisionRequirementOut],
)
def list_revision_requirements(
    revision_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> list[RevisionRequirementOut]:
    """이 개정판의 각 섹션이 근거로 삼은 요건."""
    db: Session = ctx.db
    revision = doc_svc.get_revision(db, revision_id)
    document = doc_svc.get_document(db, revision.document_id)
    ctx.require("doc.read", document.system_id)
    rows = db.execute(
        select(DocumentRequirement.section_key, Requirement, SourceClause.number, SourceDocument)
        .join(Requirement, Requirement.id == DocumentRequirement.requirement_id)
        .join(SourceClause, SourceClause.id == Requirement.clause_id)
        .join(SourceDocument, SourceDocument.id == Requirement.source_id)
        .where(DocumentRequirement.revision_id == revision_id)
        .order_by(SourceDocument.code, SourceClause.position, Requirement.position)
    ).all()
    return [
        RevisionRequirementOut(
            section_key=section_key,
            requirement=_requirement_out(requirement, clause_number),
            source=_source_ref(source),
        )
        for section_key, requirement, clause_number, source in rows
    ]
