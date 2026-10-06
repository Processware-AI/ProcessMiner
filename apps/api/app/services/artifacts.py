"""기존 산출물 정합화의 업무 규칙.

흐름: 산출물을 올린다(글자를 뽑아 둔다) → 어느 양식의 기록인지 정한다(모델이 제안하고 사람이
확정한다) → 양식의 항목에 원본의 값을 옮긴다 → 사람이 확인·보완한다 → 기록으로 발행한다.

원칙
- 원본 파일은 바꾸지 않고 보관한다.
- 값은 원본에 있는 것만 옮긴다. 원본의 어디에서 왔는지 대조되지 않은 값(미검증 제안)은
  사람이 확인하기 전에는 발행할 수 없다. 원본에 없는 항목은 비워 두고 사람이 보완한다.
- 사람이 채우거나 고친 값은 원본에서 온 값과 구분해, 누가 언제 했는지 남긴다.
- 산출물을 외부 모델로 보내는 일은 회사가 동의(설정)한 뒤에만 한다. 동의하지 않아도
  양식을 직접 고르고 항목을 직접 채워 기록을 만들 수 있다.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.domain import revisions as rev
from app.errors import api_error, not_found
from app.extract.artifact import Segment, UnsupportedArtifact, extract_segments
from app.models import (
    Artifact,
    ArtifactText,
    Document,
    DocumentRevision,
    ProcessRecord,
    ProcessSystem,
    Run,
    Tenant,
)
from app.pipelines import harmonize
from app.services import audit, tailoring
from app.services.numbering import next_record_seq

ACTIVE_RUN_STATUSES = ("queued", "running")
RUN_KIND = "harmonize_artifact"


def ai_enabled(tenant: Tenant) -> bool:
    """회사가 산출물을 AI 모델로 처리하는 데 동의했는가. 기본은 꺼짐이다."""
    return bool(tenant.settings.get("artifact_ai", False))


# ── 양식 ─────────────────────────────────────────────────────────────────────


@dataclass
class Template:
    """기록을 만들 수 있는 양식: 이 체계에서 쓰는 템플릿 문서와, 지금 유효한 판."""

    doc: Document
    revision: DocumentRevision
    instruction: str  # 상위 지침의 제목
    fields: list[str]

    @property
    def approved(self) -> bool:
        return self.revision.status == rev.APPROVED


def templates(db: Session, system: ProcessSystem) -> list[Template]:
    """이 체계에서 쓰는 양식. 승인판이 있으면 승인판, 없으면 이 체계가 작성 중인 판."""
    entries = {
        e.doc.id: e for e in tailoring.effective_documents(db, system) if e.state != "excluded"
    }
    forms = [e for e in entries.values() if e.doc.doc_type == "TMP"]
    if not forms:
        return []
    revisions: dict[uuid.UUID, DocumentRevision] = {}
    for revision in db.scalars(
        select(DocumentRevision).where(
            DocumentRevision.document_id.in_([e.doc.id for e in forms]),
            DocumentRevision.status.in_((rev.APPROVED, *rev.OPEN_STATUSES)),
        )
    ):
        current = revisions.get(revision.document_id)
        if current is None or revision.status == rev.APPROVED:
            revisions[revision.document_id] = revision
    result = []
    for entry in forms:
        revision = revisions.get(entry.doc.id)
        # 상위 체계에서 아직 승인되지 않은 양식은 내려오지 않는다.
        if revision is None or (revision.status != rev.APPROVED and entry.state == "inherited"):
            continue
        parent = entries.get(entry.parent_id)
        result.append(
            Template(
                doc=entry.doc,
                revision=revision,
                instruction=parent.doc.title if parent else "",
                fields=harmonize.template_fields(revision.sections),
            )
        )
    return result


def template(db: Session, system: ProcessSystem, document_id: uuid.UUID) -> Template:
    found = next((t for t in templates(db, system) if t.doc.id == document_id), None)
    if found is None:
        raise api_error(422, "template_not_found", "이 체계에서 쓰는 양식이 아닙니다.")
    return found


# ── 산출물 ───────────────────────────────────────────────────────────────────


def get_artifact(db: Session, artifact_id: uuid.UUID) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise not_found("산출물")
    return artifact


def segments(db: Session, artifact_id: uuid.UUID) -> list[Segment]:
    row = db.get(ArtifactText, artifact_id)
    return [Segment(s["loc"], s["text"]) for s in (row.segments if row else [])]


def latest_run(db: Session, artifact_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run).where(Run.artifact_id == artifact_id).order_by(Run.created_at.desc()).limit(1)
    )


def is_busy(db: Session, artifact_id: uuid.UUID) -> bool:
    run = latest_run(db, artifact_id)
    return run is not None and run.status in ACTIVE_RUN_STATUSES


def record_of(db: Session, artifact_id: uuid.UUID) -> ProcessRecord | None:
    return db.scalar(select(ProcessRecord).where(ProcessRecord.artifact_id == artifact_id))


def register(
    db: Session, *, system: ProcessSystem, actor_id: uuid.UUID, filename: str, data: bytes
) -> Artifact:
    """산출물을 보관하고 글자를 뽑아 둔다(모델을 쓰지 않는다)."""
    name = PurePath(filename).name[:300]
    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = db.scalar(
        select(Artifact).where(Artifact.system_id == system.id, Artifact.sha256 == sha256)
    )
    if duplicate is not None:
        raise api_error(409, "duplicate_artifact", f"이미 올린 파일입니다: {duplicate.filename}")
    try:
        extracted = extract_segments(name, data)
    except UnsupportedArtifact as exc:
        raise api_error(422, "unreadable_artifact", str(exc)) from exc

    suffix = PurePath(name).suffix.lower()
    artifact = Artifact(
        tenant_id=system.tenant_id,
        system_id=system.id,
        filename=name,
        kind=suffix.lstrip("."),
        size_bytes=len(data),
        sha256=sha256,
        storage_key=storage.save(system.tenant_id, sha256, suffix, data),
        char_count=sum(len(s.text) for s in extracted),
        title=PurePath(name).stem[:300],
        uploaded_by=actor_id,
    )
    db.add(artifact)
    db.flush()
    db.add(
        ArtifactText(
            artifact_id=artifact.id,
            tenant_id=system.tenant_id,
            segments=[{"loc": s.loc, "text": s.text} for s in extracted],
        )
    )
    db.flush()
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="artifact.upload",
        entity_type="artifact",
        entity_id=artifact.id,
        data={"system": system.slug, "filename": name, "sha256": sha256},
    )
    return artifact


def _require_idle(db: Session, artifact: Artifact) -> None:
    if is_busy(db, artifact.id):
        raise api_error(409, "run_in_progress", "처리가 끝난 뒤에 할 수 있습니다.")
    record = record_of(db, artifact.id)
    if record is not None and record.status == "published":
        raise api_error(409, "already_published", "이미 기록으로 발행한 산출물입니다.")


def _queue(db: Session, artifact: Artifact, step: str, actor_id: uuid.UUID) -> Run:
    run = Run(
        tenant_id=artifact.tenant_id,
        kind=RUN_KIND,
        status="queued",
        artifact_id=artifact.id,
        progress={"step": step},
        started_by=actor_id,
    )
    db.add(run)
    db.flush()
    return run


def start_matching(db: Session, *, tenant: Tenant, artifact: Artifact, actor_id: uuid.UUID) -> Run:
    """모델에게 어느 양식의 기록인지 묻는다. 일치도가 높으면 항목 값까지 이어서 뽑는다."""
    if not ai_enabled(tenant):
        raise api_error(
            409,
            "ai_not_enabled",
            "산출물의 AI 처리가 꺼져 있습니다. 회사 설정에서 켜거나, 양식을 직접 고르세요.",
        )
    _require_idle(db, artifact)
    return _queue(db, artifact, "match", actor_id)


def set_template(
    db: Session,
    *,
    tenant: Tenant,
    system: ProcessSystem,
    artifact: Artifact,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """사람이 양식을 확정한다. 이어서 항목 값을 뽑는다(AI 처리가 꺼져 있으면 빈 기록을 만든다)."""
    _require_idle(db, artifact)
    chosen = template(db, system, document_id)

    record = record_of(db, artifact.id)
    if record is not None and record.template_document_id != chosen.doc.id:
        db.delete(record)  # 다른 양식으로 뽑은 초안은 쓸모가 없다
        db.flush()
        record = None
    proposed = next(
        (c for c in artifact.candidates if c.get("document_id") == str(chosen.doc.id)), None
    )
    artifact.template_document_id = chosen.doc.id
    artifact.match_confidence = proposed["confidence"] if proposed else None
    artifact.match_state = "confirmed"
    artifact.confirmed_by = actor_id
    artifact.confirmed_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        tenant_id=artifact.tenant_id,
        actor_id=actor_id,
        action="artifact.match",
        entity_type="artifact",
        entity_id=artifact.id,
        data={
            "filename": artifact.filename,
            "template": chosen.doc.code,
            "confidence": artifact.match_confidence,
        },
    )
    if ai_enabled(tenant):
        _queue(db, artifact, "normalize", actor_id)
    elif record is None:
        save_draft(db, artifact=artifact, chosen=chosen, values=None, model=None, actor_id=actor_id)


def save_draft(
    db: Session,
    *,
    artifact: Artifact,
    chosen: Template,
    values: list[harmonize.FieldValue] | None,
    model: str | None,
    actor_id: uuid.UUID | None,
) -> ProcessRecord:
    """산출물의 기록 초안을 만들거나 새 값으로 바꾼다. values 가 없으면 모든 항목이 빈 초안."""
    by_name = {v.name: v for v in values or []}
    fields = []
    for name in chosen.fields:
        value = by_name.get(name)
        filled = value is not None and bool(value.value)
        fields.append(
            {
                "name": name,
                "value": value.value if filled else "",
                "source": "artifact" if filled else "empty",
                "quote": value.quote if filled else "",
                "location": value.location if filled else "",
                "verified": bool(filled and value.verified),
            }
        )
    record = record_of(db, artifact.id)
    if record is None:
        record = ProcessRecord(
            tenant_id=artifact.tenant_id,
            system_id=artifact.system_id,
            artifact_id=artifact.id,
            template_document_id=chosen.doc.id,
            template_revision_id=chosen.revision.id,
            legacy=True,
            created_by=actor_id,
        )
        db.add(record)
    record.template_document_id = chosen.doc.id
    record.template_revision_id = chosen.revision.id
    record.title = artifact.title
    record.performed_on = artifact.performed_on
    record.fields = fields
    record.generated_by = model
    db.flush()
    return record


def delete(db: Session, *, artifact: Artifact, actor_id: uuid.UUID) -> None:
    """산출물을 지운다. 기록으로 발행한 뒤에는 지울 수 없다(기록의 근거다)."""
    _require_idle(db, artifact)
    record = record_of(db, artifact.id)
    if record is not None:
        db.delete(record)
    key, filename = artifact.storage_key, artifact.filename
    db.delete(artifact)
    db.flush()
    # 같은 파일을 다른 체계에서도 쓰고 있으면 파일은 남긴다.
    if db.scalar(select(Artifact.id).where(Artifact.storage_key == key).limit(1)) is None:
        storage.delete(key)
    audit.record(
        db,
        tenant_id=artifact.tenant_id,
        actor_id=actor_id,
        action="artifact.delete",
        entity_type="artifact",
        entity_id=artifact.id,
        data={"filename": filename},
    )


# ── 기록 ─────────────────────────────────────────────────────────────────────


def get_record(db: Session, record_id: uuid.UUID) -> ProcessRecord:
    record = db.get(ProcessRecord, record_id)
    if record is None:
        raise not_found("기록")
    return record


def needs_check(field: dict) -> bool:
    """원본에서 옮겼지만 원본과 대조되지 않았고, 사람이 아직 확인하지 않은 값인가."""
    return field["source"] == "artifact" and not field["verified"] and not field.get("confirmed_by")


def counts(record: ProcessRecord) -> dict[str, int]:
    fields = record.fields
    return {
        "total": len(fields),
        "empty": sum(f["source"] == "empty" for f in fields),
        "unverified": sum(needs_check(f) for f in fields),
        "human": sum(f["source"] == "human" for f in fields),
    }


def update_record(
    db: Session,
    *,
    record: ProcessRecord,
    actor_id: uuid.UUID,
    title: str | None,
    performed_on: date | None,
    clear_performed_on: bool,
    values: dict[str, str],
    confirm: list[str],
) -> ProcessRecord:
    """기록 초안을 고친다. 사람이 채우거나 고친 값에는 누가 언제 했는지 남긴다."""
    if record.status != "draft":
        raise api_error(409, "record_published", "발행한 기록은 고칠 수 없습니다.")
    known = {f["name"] for f in record.fields}
    unknown = (set(values) | set(confirm)) - known
    if unknown:
        raise api_error(
            422, "unknown_field", f"양식에 없는 항목입니다: {', '.join(sorted(unknown))}"
        )

    now = datetime.now(UTC).isoformat()
    fields = []
    for field in record.fields:
        field = dict(field)
        name = field["name"]
        if name in values and values[name].strip() != field["value"]:
            if field["source"] == "artifact" and "original" not in field:
                # 원본에서 옮긴 값을 사람이 고쳤다. 원래 제안을 남겨 둔다.
                field["original"] = {
                    "value": field["value"],
                    "quote": field["quote"],
                    "location": field["location"],
                }
            field["value"] = values[name].strip()
            field["source"] = "human" if field["value"] else "empty"
            field["filled_by"], field["filled_at"] = str(actor_id), now
        elif name in confirm and needs_check(field):
            field["confirmed_by"], field["confirmed_at"] = str(actor_id), now
        fields.append(field)
    record.fields = fields
    if title is not None:
        record.title = title.strip()
    if performed_on is not None:
        record.performed_on = performed_on
    elif clear_performed_on:
        record.performed_on = None
    db.flush()
    return record


def publish(
    db: Session, *, system: ProcessSystem, record: ProcessRecord, actor_id: uuid.UUID
) -> ProcessRecord:
    """기록으로 발행한다. 이후에는 바뀌지 않는다. 번호는 이때 발급한다."""
    if record.status != "draft":
        raise api_error(409, "record_published", "이미 발행한 기록입니다.")
    if not record.title.strip():
        raise api_error(422, "title_required", "기록의 제목을 입력하세요.")
    tally = counts(record)
    if tally["unverified"]:
        raise api_error(
            409,
            "unverified_fields",
            f"원본과 대조되지 않은 값이 {tally['unverified']}개 있습니다. "
            "원본을 보고 확인하거나 고친 뒤 발행하세요.",
        )
    if tally["empty"] == tally["total"]:
        raise api_error(409, "empty_record", "채워진 항목이 하나도 없습니다.")

    form = db.get(Document, record.template_document_id)
    seq = next_record_seq(db, system.tenant_id, system.root_system_id, form.code)
    record.code = f"REC-{form.code.removeprefix('TMP-')}-{seq:03d}"
    record.status = "published"
    record.published_by = actor_id
    record.published_at = datetime.now(UTC)
    db.flush()
    artifact = db.get(Artifact, record.artifact_id) if record.artifact_id else None
    audit.record(
        db,
        tenant_id=system.tenant_id,
        actor_id=actor_id,
        action="record.publish",
        entity_type="record",
        entity_id=record.id,
        data={
            "system": system.slug,
            "code": record.code,
            "template": form.code,
            "legacy": record.legacy,
            "empty_fields": tally["empty"],
            "source_file": artifact.filename if artifact else None,
            "source_sha256": artifact.sha256 if artifact else None,
        },
    )
    return record
