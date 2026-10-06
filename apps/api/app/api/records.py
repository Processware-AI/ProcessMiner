"""기존 산출물 정합화와 기록."""

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select

from app.api.sources import _run_out
from app.config import get_settings
from app.db import CommitRoute
from app.deps import TenantContext, tenant_context
from app.domain import revisions as rev
from app.errors import api_error
from app.models import (
    AppUser,
    Artifact,
    Document,
    DocumentRevision,
    ProcessRecord,
    ProcessSystem,
)
from app.schemas import (
    ArtifactDetail,
    ArtifactOut,
    ArtifactTemplateIn,
    DocumentRef,
    MatchCandidateOut,
    RecordCounts,
    RecordField,
    RecordOut,
    RecordPatch,
    RecordSummary,
    RecordTemplateOut,
    SegmentOut,
    UserRef,
)
from app.services import artifacts as svc

router = APIRouter(prefix="/api", tags=["records"], route_class=CommitRoute)

_SYSTEM = "/t/{tenant_slug}/systems/{system_slug}"


def _ref(doc: Document) -> DocumentRef:
    return DocumentRef(id=doc.id, code=doc.code, title=doc.title, doc_type=doc.doc_type)


def _summary(record: ProcessRecord | None) -> RecordSummary | None:
    if record is None:
        return None
    return RecordSummary(
        id=record.id,
        code=record.code,
        title=record.title,
        status=record.status,
        counts=RecordCounts(**svc.counts(record)),
    )


def _artifact_out(ctx: TenantContext, artifact: Artifact) -> ArtifactOut:
    db = ctx.db
    run = svc.latest_run(db, artifact.id)
    busy = run is not None and run.status in svc.ACTIVE_RUN_STATUSES
    record = svc.record_of(db, artifact.id)
    form = (
        db.get(Document, artifact.template_document_id) if artifact.template_document_id else None
    )

    if busy:
        state = "processing"
    elif record is not None:
        state = "published" if record.status == "published" else "review"
    elif artifact.match_state == "proposed":
        state = "needs_confirm"
    else:
        state = "needs_template"

    actions: list[str] = []
    published = record is not None and record.status == "published"
    if ctx.can("record.manage", artifact.system_id) and not busy and not published:
        if svc.ai_enabled(ctx.tenant):
            actions.append("match")
        actions += ["set_template", "delete"]

    return ArtifactOut(
        id=artifact.id,
        filename=artifact.filename,
        kind=artifact.kind,
        size_bytes=artifact.size_bytes,
        char_count=artifact.char_count,
        title=artifact.title,
        performed_on=artifact.performed_on,
        state=state,
        match_state=artifact.match_state,
        template=_ref(form) if form else None,
        match_confidence=artifact.match_confidence,
        candidates=[
            MatchCandidateOut(
                document=DocumentRef(
                    id=c["document_id"], code=c["code"], title=c["title"], doc_type="TMP"
                ),
                confidence=c["confidence"],
                reason=c["reason"],
            )
            for c in artifact.candidates
        ],
        record=_summary(record),
        run=_run_out(db, run),
        created_at=artifact.created_at,
        actions=actions,
    )


def _record_out(ctx: TenantContext, record: ProcessRecord) -> RecordOut:
    db = ctx.db
    form = db.get(Document, record.template_document_id)
    revision = db.get(DocumentRevision, record.template_revision_id)
    artifact = db.get(Artifact, record.artifact_id) if record.artifact_id else None
    users = {
        u.id: UserRef(id=u.id, name=u.name)
        for u in db.scalars(
            select(AppUser).where(
                AppUser.id.in_(
                    {record.published_by, record.created_by}
                    | {
                        uuid.UUID(f[key])
                        for f in record.fields
                        for key in ("filled_by", "confirmed_by")
                        if f.get(key)
                    }
                )
            )
        )
    }

    def who(value: str | None) -> UserRef | None:
        return users.get(uuid.UUID(value)) if value else None

    tally = svc.counts(record)
    actions: list[str] = []
    if record.status == "draft" and ctx.can("record.manage", record.system_id):
        actions.append("edit")
        if not tally["unverified"] and tally["empty"] < tally["total"]:
            actions.append("publish")
    return RecordOut(
        id=record.id,
        code=record.code,
        title=record.title,
        status=record.status,
        legacy=record.legacy,
        performed_on=record.performed_on,
        template=_ref(form),
        template_version=revision.version,
        template_approved=revision.status in (rev.APPROVED, rev.SUPERSEDED),
        artifact_id=artifact.id if artifact else None,
        artifact_filename=artifact.filename if artifact else None,
        fields=[
            RecordField(
                name=f["name"],
                value=f["value"],
                source=f["source"],
                quote=f.get("quote", ""),
                location=f.get("location", ""),
                verified=f.get("verified", False),
                needs_check=svc.needs_check(f),
                original_value=(f.get("original") or {}).get("value"),
                filled_by=who(f.get("filled_by")),
                filled_at=f.get("filled_at"),
                confirmed_by=who(f.get("confirmed_by")),
            )
            for f in record.fields
        ],
        counts=RecordCounts(**tally),
        generated_by=record.generated_by,
        created_at=record.created_at,
        published_at=record.published_at,
        published_by=who(str(record.published_by) if record.published_by else None),
        actions=actions,
    )


# ── 양식 ─────────────────────────────────────────────────────────────────────


@router.get(f"{_SYSTEM}/record-templates", response_model=list[RecordTemplateOut])
def list_record_templates(
    system_slug: str, ctx: TenantContext = Depends(tenant_context)
) -> list[RecordTemplateOut]:
    """이 체계에서 기록을 만들 수 있는 양식."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    return [
        RecordTemplateOut(
            document=_ref(form.doc),
            instruction=form.instruction,
            version=form.revision.version,
            approved=form.approved,
            fields=form.fields,
        )
        for form in svc.templates(ctx.db, system)
    ]


# ── 산출물 ───────────────────────────────────────────────────────────────────


@router.get(f"{_SYSTEM}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(
    system_slug: str, ctx: TenantContext = Depends(tenant_context)
) -> list[ArtifactOut]:
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    rows = ctx.db.scalars(
        select(Artifact).where(Artifact.system_id == system.id).order_by(Artifact.created_at.desc())
    )
    return [_artifact_out(ctx, artifact) for artifact in rows]


@router.post(f"{_SYSTEM}/artifacts", response_model=ArtifactOut, status_code=201)
def upload_artifact(
    system_slug: str,
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(tenant_context),
) -> ArtifactOut:
    """산출물을 올린다. 올리는 즉시 글자를 뽑아 두고, AI 처리가 켜져 있으면 양식을 찾기 시작한다."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("record.manage", system.id)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise api_error(
            413,
            "file_too_large",
            f"파일이 너무 큽니다. {get_settings().max_upload_mb}MB 까지 올릴 수 있습니다.",
        )
    artifact = svc.register(
        ctx.db,
        system=system,
        actor_id=ctx.user.id,
        filename=file.filename or "artifact",
        data=data,
    )
    if svc.ai_enabled(ctx.tenant):
        svc.start_matching(ctx.db, tenant=ctx.tenant, artifact=artifact, actor_id=ctx.user.id)
    return _artifact_out(ctx, artifact)


def _artifact_for(ctx: TenantContext, artifact_id: uuid.UUID, action: str) -> Artifact:
    artifact = svc.get_artifact(ctx.db, artifact_id)
    ctx.require(action, artifact.system_id)
    return artifact


@router.get("/t/{tenant_slug}/artifacts/{artifact_id}", response_model=ArtifactDetail)
def get_artifact(
    artifact_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> ArtifactDetail:
    artifact = _artifact_for(ctx, artifact_id, "doc.read")
    return ArtifactDetail(
        **_artifact_out(ctx, artifact).model_dump(),
        segments=[SegmentOut(loc=s.loc, text=s.text) for s in svc.segments(ctx.db, artifact.id)],
    )


@router.post("/t/{tenant_slug}/artifacts/{artifact_id}/match", response_model=ArtifactOut)
def match_artifact(
    artifact_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)
) -> ArtifactOut:
    """어느 양식의 기록인지 모델에게 (다시) 묻는다."""
    artifact = _artifact_for(ctx, artifact_id, "record.manage")
    svc.start_matching(ctx.db, tenant=ctx.tenant, artifact=artifact, actor_id=ctx.user.id)
    return _artifact_out(ctx, artifact)


@router.put("/t/{tenant_slug}/artifacts/{artifact_id}/template", response_model=ArtifactOut)
def set_artifact_template(
    artifact_id: uuid.UUID,
    payload: ArtifactTemplateIn,
    ctx: TenantContext = Depends(tenant_context),
) -> ArtifactOut:
    """양식을 확정한다(모델의 제안을 받아들이거나 직접 고른다). 이어서 항목 값을 뽑는다."""
    artifact = _artifact_for(ctx, artifact_id, "record.manage")
    svc.set_template(
        ctx.db,
        tenant=ctx.tenant,
        system=ctx.db.get(ProcessSystem, artifact.system_id),
        artifact=artifact,
        document_id=payload.document_id,
        actor_id=ctx.user.id,
    )
    return _artifact_out(ctx, artifact)


@router.delete("/t/{tenant_slug}/artifacts/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> None:
    artifact = _artifact_for(ctx, artifact_id, "record.manage")
    svc.delete(ctx.db, artifact=artifact, actor_id=ctx.user.id)


# ── 기록 ─────────────────────────────────────────────────────────────────────


@router.get(f"{_SYSTEM}/records", response_model=list[RecordOut])
def list_records(system_slug: str, ctx: TenantContext = Depends(tenant_context)) -> list[RecordOut]:
    """발행한 기록. 최근 것이 먼저."""
    system = ctx.system_by_slug(system_slug)
    ctx.require("doc.read", system.id)
    rows = ctx.db.scalars(
        select(ProcessRecord)
        .where(ProcessRecord.system_id == system.id, ProcessRecord.status == "published")
        .order_by(ProcessRecord.published_at.desc())
    )
    return [_record_out(ctx, record) for record in rows]


@router.get("/t/{tenant_slug}/records/{record_id}", response_model=RecordOut)
def get_record(record_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> RecordOut:
    record = svc.get_record(ctx.db, record_id)
    ctx.require("doc.read", record.system_id)
    return _record_out(ctx, record)


@router.patch("/t/{tenant_slug}/records/{record_id}", response_model=RecordOut)
def update_record(
    record_id: uuid.UUID, payload: RecordPatch, ctx: TenantContext = Depends(tenant_context)
) -> RecordOut:
    record = svc.get_record(ctx.db, record_id)
    ctx.require("record.manage", record.system_id)
    svc.update_record(
        ctx.db,
        record=record,
        actor_id=ctx.user.id,
        title=payload.title,
        performed_on=payload.performed_on,
        clear_performed_on="performed_on" in payload.model_fields_set
        and payload.performed_on is None,
        values={f.name: f.value for f in payload.fields},
        confirm=payload.confirm,
    )
    return _record_out(ctx, record)


@router.post("/t/{tenant_slug}/records/{record_id}/publish", response_model=RecordOut)
def publish_record(record_id: uuid.UUID, ctx: TenantContext = Depends(tenant_context)) -> RecordOut:
    record = svc.get_record(ctx.db, record_id)
    ctx.require("record.manage", record.system_id)
    svc.publish(
        ctx.db,
        system=ctx.db.get(ProcessSystem, record.system_id),
        record=record,
        actor_id=ctx.user.id,
    )
    return _record_out(ctx, record)
