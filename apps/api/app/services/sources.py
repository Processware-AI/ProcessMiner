"""원문 등록과 요건 확정의 업무 규칙.

원문을 올리면 그 자리에서 쪽별 본문을 뽑고 조항으로 나눈다(모델을 쓰지 않는다).
요건 도출은 오래 걸리므로 작업(run)으로 대기열에 넣고 작업자가 처리한다.
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from pathlib import PurePath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import storage
from app.errors import api_error, not_found
from app.extract.pdf import extract_pages
from app.extract.structure import segment_clauses
from app.models import Requirement, Run, SourceClause, SourceDocument, SourcePage
from app.pipelines.mining import has_obligation
from app.services import audit

_PDF_MAGIC = b"%PDF-"
ACTIVE_RUN_STATUSES = ("queued", "running")


def get_source(db: Session, source_id: uuid.UUID) -> SourceDocument:
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise not_found("원문")
    return source


def register(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    filename: str,
    data: bytes,
    title: str,
    code: str,
    edition: str,
) -> SourceDocument:
    """원문을 저장하고 조항까지 분석해 둔다."""
    if not data.startswith(_PDF_MAGIC):
        raise api_error(422, "unsupported_file", "지금은 PDF 파일만 올릴 수 있습니다.")
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,31}", code):
        raise api_error(
            422, "invalid_code", "문서 약칭은 영문 대문자·숫자로 2~32자여야 합니다. 예: IEC62304"
        )

    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = db.scalar(select(SourceDocument).where(SourceDocument.sha256 == sha256))
    if duplicate is not None:
        raise api_error(409, "duplicate_source", f"이미 등록된 파일입니다: {duplicate.title}")

    try:
        pages = extract_pages(data)
    except ValueError as exc:
        raise api_error(422, "unreadable_pdf", str(exc)) from exc
    except Exception as exc:  # 손상된 PDF 는 라이브러리마다 다른 예외를 낸다
        raise api_error(
            422, "unreadable_pdf", "PDF 를 읽지 못했습니다. 파일이 손상됐을 수 있습니다."
        ) from exc

    readable = [p for p in pages if not p.sparse]
    if len(readable) < max(1, len(pages) // 2):
        raise api_error(
            422,
            "no_text_layer",
            "글자를 읽을 수 없는 PDF 입니다(스캔 이미지로 보입니다). "
            "문자 인식은 아직 지원하지 않습니다.",
        )
    clauses = segment_clauses(pages)
    if not clauses:
        raise api_error(
            422,
            "no_clauses",
            "조항 번호(1, 1.1 …)를 찾지 못했습니다. 번호 체계가 있는 표준·법규 문서만 지원합니다.",
        )

    source = SourceDocument(
        tenant_id=tenant_id,
        title=title.strip(),
        code=code,
        edition=edition.strip(),
        filename=PurePath(filename).name[:300],
        size_bytes=len(data),
        sha256=sha256,
        storage_key=storage.save(tenant_id, sha256, ".pdf", data),
        page_count=len(pages),
        sparse_pages=[p.page_no for p in pages if p.sparse],
        status="extracted",
        uploaded_by=actor_id,
    )
    db.add(source)
    db.flush()
    db.add_all(
        SourcePage(source_id=source.id, page_no=p.page_no, tenant_id=tenant_id, text=p.text)
        for p in pages
    )
    db.add_all(
        SourceClause(
            tenant_id=tenant_id,
            source_id=source.id,
            number=clause.number,
            title=clause.title[:300],
            kind=clause.kind,
            normative=clause.normative,
            level=clause.level,
            parent_number=clause.parent_number,
            page_start=clause.page_start,
            page_end=clause.page_end,
            position=position,
            has_obligation=clause.normative and has_obligation(clause),
            text=clause.text,
        )
        for position, clause in enumerate(clauses)
    )
    db.flush()
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="source.upload",
        entity_type="source",
        entity_id=source.id,
        data={"title": source.title, "code": code, "sha256": sha256, "pages": len(pages)},
    )
    return source


def active_run(db: Session, source_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run)
        .where(Run.source_id == source_id, Run.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(Run.created_at.desc())
    )


def latest_run(db: Session, source_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run).where(Run.source_id == source_id).order_by(Run.created_at.desc()).limit(1)
    )


def start_mining(db: Session, *, source: SourceDocument, actor_id: uuid.UUID) -> Run:
    if source.status == "confirmed":
        raise api_error(409, "already_confirmed", "이미 요건을 확정한 원문입니다.")
    if active_run(db, source.id) is not None:
        raise api_error(409, "run_in_progress", "이미 요건을 도출하고 있습니다.")

    run = Run(
        tenant_id=source.tenant_id,
        kind="mine_requirements",
        status="queued",
        source_id=source.id,
        started_by=actor_id,
    )
    db.add(run)
    source.status = "mining"
    db.flush()
    audit.record(
        db,
        tenant_id=source.tenant_id,
        actor_id=actor_id,
        action="source.mine",
        entity_type="source",
        entity_id=source.id,
        data={"title": source.title, "run": str(run.id)},
    )
    return run


def requirement_counts(db: Session, source_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(Requirement.status, Requirement.quote_verified, func.count())
        .where(Requirement.source_id == source_id)
        .group_by(Requirement.status, Requirement.quote_verified)
    ).all()
    counts = {"proposed": 0, "confirmed": 0, "rejected": 0, "unverified": 0}
    for status, verified, n in rows:
        counts[status] += n
        if not verified and status != "rejected":
            counts["unverified"] += n
    return counts


def confirm(db: Session, *, source: SourceDocument, actor_id: uuid.UUID) -> SourceDocument:
    """검토를 마친 요건을 확정한다. 이후에는 요건을 고칠 수 없고, 문서 생성의 근거가 된다."""
    if source.status == "confirmed":
        raise api_error(409, "already_confirmed", "이미 요건을 확정한 원문입니다.")
    if active_run(db, source.id) is not None:
        raise api_error(409, "run_in_progress", "요건 도출이 끝난 뒤에 확정할 수 있습니다.")

    counts = requirement_counts(db, source.id)
    if counts["proposed"] == 0:
        raise api_error(
            409, "nothing_to_confirm", "확정할 요건이 없습니다. 먼저 요건을 도출하세요."
        )
    if counts["unverified"] > 0:
        raise api_error(
            409,
            "unverified_requirements",
            f"원문에서 인용이 확인되지 않은 요건이 {counts['unverified']}건 있습니다. "
            "근거 없는 요건은 확정할 수 없으니 제외한 뒤 다시 확정하세요.",
        )
    failed = sorted(unit for unit, state in source.mining_state.items() if state == "failed")
    if failed:
        raise api_error(
            409,
            "mining_incomplete",
            f"도출에 실패한 절이 있습니다({', '.join(failed)}). 다시 도출한 뒤 확정하세요.",
        )

    for requirement in db.scalars(
        select(Requirement).where(
            Requirement.source_id == source.id, Requirement.status == "proposed"
        )
    ):
        requirement.status = "confirmed"
    source.status = "confirmed"
    source.confirmed_by = actor_id
    source.confirmed_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        tenant_id=source.tenant_id,
        actor_id=actor_id,
        action="source.confirm",
        entity_type="source",
        entity_id=source.id,
        data={
            "title": source.title,
            "confirmed": counts["proposed"],
            "rejected": counts["rejected"],
        },
    )
    return source


def delete(db: Session, *, source: SourceDocument, actor_id: uuid.UUID) -> None:
    if source.status == "confirmed":
        raise api_error(
            409,
            "already_confirmed",
            "요건을 확정한 원문은 삭제할 수 없습니다(문서의 근거로 쓰입니다).",
        )
    if active_run(db, source.id) is not None:
        raise api_error(409, "run_in_progress", "요건 도출이 끝난 뒤에 삭제할 수 있습니다.")
    storage_key = source.storage_key
    db.delete(source)
    db.flush()
    storage.delete(storage_key)
    audit.record(
        db,
        tenant_id=source.tenant_id,
        actor_id=actor_id,
        action="source.delete",
        entity_type="source",
        entity_id=source.id,
        data={"title": source.title},
    )
