"""원문 등록, 조항 열람, 요건 도출·검토·확정."""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import CommitRoute
from app.deps import TenantContext, tenant_context
from app.errors import api_error, not_found
from app.models import AppUser, Requirement, Run, RunEvent, SourceClause, SourceDocument
from app.schemas import (
    ClauseDetail,
    ClauseSummary,
    RequirementCounts,
    RequirementOut,
    RequirementPatch,
    RunOut,
    SourceOut,
    UserRef,
)
from app.services import sources as svc

router = APIRouter(prefix="/api", tags=["sources"], route_class=CommitRoute)

_EVENT_TAIL = 8


def _run_out(db: Session, run: Run | None) -> RunOut | None:
    if run is None:
        return None
    events = db.scalars(
        select(RunEvent.message)
        .where(RunEvent.run_id == run.id)
        .order_by(RunEvent.id.desc())
        .limit(_EVENT_TAIL)
    ).all()
    return RunOut(
        id=run.id,
        kind=run.kind,
        status=run.status,
        progress=run.progress,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        events=list(reversed(events)),
    )


def _source_out(ctx: TenantContext, source: SourceDocument) -> SourceOut:
    db = ctx.db
    clause_count, obligation_count = db.execute(
        select(
            func.count(),
            func.count().filter(SourceClause.has_obligation),
        ).where(SourceClause.source_id == source.id)
    ).one()
    users = {
        u.id: UserRef(id=u.id, name=u.name)
        for u in db.scalars(
            select(AppUser).where(AppUser.id.in_({source.uploaded_by, source.confirmed_by}))
        )
    }
    counts = svc.requirement_counts(db, source.id)
    run = svc.latest_run(db, source.id)
    busy = run is not None and run.status in svc.ACTIVE_RUN_STATUSES
    failed_units = sorted(u for u, state in source.mining_state.items() if state == "failed")

    # 화면은 이 목록으로 버튼을 정한다.
    actions: list[str] = []
    if ctx.can("source.manage") and source.status != "confirmed" and not busy:
        # 아직 도출하지 않았거나(중단 포함) 실패한 절이 남아 있으면 도출할 수 있다.
        if obligation_count > 0 and (source.status == "extracted" or failed_units):
            actions.append("mine")
        if counts["proposed"] > 0:
            actions += ["review", "confirm"]
        actions.append("delete")

    return SourceOut(
        id=source.id,
        title=source.title,
        code=source.code,
        edition=source.edition,
        filename=source.filename,
        size_bytes=source.size_bytes,
        page_count=source.page_count,
        sparse_pages=source.sparse_pages,
        status=source.status,
        clause_count=clause_count,
        obligation_clause_count=obligation_count,
        requirements=RequirementCounts(**counts),
        failed_units=failed_units,
        uploaded_by=users.get(source.uploaded_by),
        created_at=source.created_at,
        confirmed_by=users.get(source.confirmed_by),
        confirmed_at=source.confirmed_at,
        run=_run_out(db, run),
        actions=actions,
    )


# ── 원문 ─────────────────────────────────────────────────────────────────────


@router.get("/t/{tenant_slug}/sources", response_model=list[SourceOut])
def list_sources(ctx: TenantContext = Depends(tenant_context)) -> list[SourceOut]:
    ctx.require("source.read")
    rows = ctx.db.scalars(select(SourceDocument).order_by(SourceDocument.created_at.desc()))
    return [_source_out(ctx, source) for source in rows]


@router.post("/t/{tenant_slug}/sources", response_model=SourceOut, status_code=201)
def upload_source(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=300),
    code: str = Form(...),
    edition: str = Form(default="", max_length=100),
    ctx: TenantContext = Depends(tenant_context),
) -> SourceOut:
    """원문을 올린다. 올리는 즉시 본문을 뽑고 조항으로 나눈다."""
    ctx.require("source.manage")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise api_error(
            413,
            "file_too_large",
            f"파일이 너무 큽니다. {get_settings().max_upload_mb}MB 까지 올릴 수 있습니다.",
        )
    source = svc.register(
        ctx.db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        filename=file.filename or "source.pdf",
        data=data,
        title=title,
        code=code,
        edition=edition,
    )
    return _source_out(ctx, source)


@router.get("/t/{tenant_slug}/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> SourceOut:
    ctx.require("source.read")
    return _source_out(ctx, svc.get_source(ctx.db, source_id))


@router.delete("/t/{tenant_slug}/sources/{source_id}", status_code=204)
def delete_source(source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> None:
    ctx.require("source.manage")
    svc.delete(ctx.db, source=svc.get_source(ctx.db, source_id), actor_id=ctx.user.id)


@router.post("/t/{tenant_slug}/sources/{source_id}/mine", response_model=SourceOut)
def mine_source(source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> SourceOut:
    """요건 도출을 시작한다. 작업은 대기열에 들어가고 작업자가 처리한다."""
    ctx.require("source.manage")
    source = svc.get_source(ctx.db, source_id)
    svc.start_mining(ctx.db, source=source, actor_id=ctx.user.id)
    return _source_out(ctx, source)


@router.post("/t/{tenant_slug}/sources/{source_id}/confirm", response_model=SourceOut)
def confirm_source(source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> SourceOut:
    ctx.require("source.manage")
    source = svc.confirm(ctx.db, source=svc.get_source(ctx.db, source_id), actor_id=ctx.user.id)
    return _source_out(ctx, source)


# ── 조항과 요건 ──────────────────────────────────────────────────────────────


def _clause_summaries(db: Session, *conditions) -> list[ClauseSummary]:
    live = Requirement.status != "rejected"
    rows = db.execute(
        select(
            SourceClause,
            func.count(Requirement.id).filter(live),
            func.count(Requirement.id).filter(live, Requirement.quote_verified.is_(False)),
        )
        .outerjoin(Requirement, Requirement.clause_id == SourceClause.id)
        .where(*conditions)
        .group_by(SourceClause.id)
        .order_by(SourceClause.position)
    ).all()
    return [
        ClauseSummary(
            id=clause.id,
            number=clause.number,
            title=clause.title,
            kind=clause.kind,
            normative=clause.normative,
            level=clause.level,
            parent_number=clause.parent_number,
            page_start=clause.page_start,
            page_end=clause.page_end,
            has_obligation=clause.has_obligation,
            requirement_count=total,
            unverified_count=unverified,
        )
        for clause, total, unverified in rows
    ]


def _requirement_out(requirement: Requirement, clause_number: str) -> RequirementOut:
    return RequirementOut(
        id=requirement.id,
        clause_id=requirement.clause_id,
        clause_number=clause_number,
        code=requirement.code,
        obligation=requirement.obligation,
        category=requirement.category,
        summary=requirement.summary,
        quote=requirement.quote,
        quote_verified=requirement.quote_verified,
        page_no=requirement.page_no,
        applicability=requirement.applicability,
        evidence=requirement.evidence,
        status=requirement.status,
        generated_by=requirement.generated_by,
    )


@router.get("/t/{tenant_slug}/sources/{source_id}/clauses", response_model=list[ClauseSummary])
def list_clauses(
    source_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> list[ClauseSummary]:
    ctx.require("source.read")
    svc.get_source(ctx.db, source_id)
    return _clause_summaries(ctx.db, SourceClause.source_id == source_id)


@router.get("/t/{tenant_slug}/clauses/{clause_id}", response_model=ClauseDetail)
def get_clause(clause_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> ClauseDetail:
    ctx.require("source.read")
    clause = ctx.db.get(SourceClause, clause_id)
    if clause is None:
        raise not_found("조항")
    summary = _clause_summaries(ctx.db, SourceClause.id == clause_id)[0]
    requirements = ctx.db.scalars(
        select(Requirement).where(Requirement.clause_id == clause_id).order_by(Requirement.position)
    )
    return ClauseDetail(
        **summary.model_dump(),
        text=clause.text,
        requirements=[_requirement_out(r, clause.number) for r in requirements],
    )


@router.get(
    "/t/{tenant_slug}/sources/{source_id}/requirements", response_model=list[RequirementOut]
)
def list_requirements(
    source_id: uuid.UUID,
    unverified_only: bool = False,
    ctx: TenantContext = Depends(tenant_context),
) -> list[RequirementOut]:
    ctx.require("source.read")
    svc.get_source(ctx.db, source_id)
    query = (
        select(Requirement, SourceClause.number)
        .join(SourceClause, SourceClause.id == Requirement.clause_id)
        .where(Requirement.source_id == source_id)
        .order_by(SourceClause.position, Requirement.position)
    )
    if unverified_only:
        query = query.where(Requirement.quote_verified.is_(False), Requirement.status != "rejected")
    return [_requirement_out(r, number) for r, number in ctx.db.execute(query).all()]


@router.patch("/t/{tenant_slug}/requirements/{requirement_id}", response_model=RequirementOut)
def update_requirement(
    requirement_id: uuid.UUID,
    payload: RequirementPatch,
    ctx: TenantContext = Depends(tenant_context),
) -> RequirementOut:
    """요건을 검토한다: 요약·증적을 고치거나, 제외하거나, 제외를 되돌린다.

    원문 인용은 고칠 수 없다.
    """
    ctx.require("source.manage")
    requirement = ctx.db.get(Requirement, requirement_id)
    if requirement is None:
        raise not_found("요건")
    source = svc.get_source(ctx.db, requirement.source_id)
    if source.status == "confirmed":
        raise api_error(409, "already_confirmed", "확정한 요건은 고칠 수 없습니다.")

    if payload.summary is not None:
        requirement.summary = payload.summary.strip()
    if payload.evidence is not None:
        requirement.evidence = [e.strip() for e in payload.evidence if e.strip()]
    if payload.status is not None:
        requirement.status = payload.status
    requirement.edited_by = ctx.user.id
    ctx.db.flush()
    clause = ctx.db.get(SourceClause, requirement.clause_id)
    return _requirement_out(requirement, clause.number)
