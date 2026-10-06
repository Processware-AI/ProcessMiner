"""대기 중인 작업(run)을 하나씩 꺼내 실행한다.

개발 환경에서는 API 프로세스 안의 스레드로 돌고(설정 run_worker_in_api),
운영에서는 `python -m app.worker` 로 따로 띄울 수 있다. 대기열은 DB 의 run 테이블이다.
"""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import generation_jobs, harmonize_jobs
from app.config import get_settings
from app.db import get_engine, get_sessionmaker, set_tenant
from app.extract.structure import Clause
from app.llm import LLMError
from app.models import Requirement, Run, RunEvent, SourceClause, SourceDocument
from app.pipelines import mining

logger = logging.getLogger(__name__)

_IDLE_SECONDS = 1.5


def _log(db: Session, run: Run, message: str, level: str = "info") -> None:
    db.add(RunEvent(tenant_id=run.tenant_id, run_id=run.id, level=level, message=message))


def _finish(db: Session, run: Run, status: str, error: str = "") -> None:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)


# ── 요건 도출 ────────────────────────────────────────────────────────────────


def _to_clause(row: SourceClause) -> Clause:
    return Clause(
        number=row.number,
        title=row.title,
        kind=row.kind,
        normative=row.normative,
        page_start=row.page_start,
        page_end=row.page_end,
        lines=row.text.splitlines(),
    )


def _store_unit(
    db: Session,
    run: Run,
    source: SourceDocument,
    unit: mining.MiningUnit,
    rows: dict[str, SourceClause],
    verified: list[mining.VerifiedRequirement],
    model: str,
    next_position: int,
) -> int:
    """한 절에서 나온 요건을 저장한다. 저장한 건수를 돌려준다."""
    per_clause: dict[str, int] = {}
    for offset, item in enumerate(verified):
        # 인용이 확인되지 않았으면 모델이 적은 조항에 붙여 두되, 근거 없음으로 표시한다.
        number = item.clause_number or item.mined.clause.strip()
        row = rows.get(number) or rows[unit.clauses[0].number]
        per_clause[row.number] = per_clause.get(row.number, 0) + 1
        db.add(
            Requirement(
                tenant_id=source.tenant_id,
                source_id=source.id,
                clause_id=row.id,
                code=f"{row.number}-{per_clause[row.number]:02d}",
                position=next_position + offset,
                obligation=item.mined.obligation,
                category=item.mined.category,
                summary=item.mined.summary.strip(),
                quote=item.mined.quote.strip(),
                quote_verified=item.verified,
                page_no=item.page_no,
                applicability=item.mined.applicability.strip()[:200],
                evidence=[e.strip() for e in item.mined.evidence if e.strip()],
                generated_by=model,
            )
        )
    return len(verified)


def run_mining(db: Session, run: Run) -> None:
    source = db.get(SourceDocument, run.source_id)
    if source is None:
        _finish(db, run, "failed", "원문을 찾을 수 없습니다.")
        return

    rows = {
        row.number: row
        for row in db.scalars(
            select(SourceClause)
            .where(SourceClause.source_id == source.id)
            .order_by(SourceClause.position)
        )
    }
    units = [
        unit
        for unit in mining.build_units([_to_clause(row) for row in rows.values()])
        if source.mining_state.get(unit.number) != "done"
    ]
    progress = {"done": 0, "failed": 0, "total": len(units), "input_tokens": 0, "output_tokens": 0}
    run.progress = dict(progress)
    _log(db, run, f"요건을 도출할 절 {len(units)}개")
    db.commit()

    position = (
        db.scalar(
            select(Requirement.position)
            .where(Requirement.source_id == source.id)
            .order_by(Requirement.position.desc())
            .limit(1)
        )
        or 0
    ) + 1
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=max(1, get_settings().llm_concurrency)) as pool:
        futures = {pool.submit(mining.mine_unit, unit): unit for unit in units}
        for future in as_completed(futures):
            unit = futures[future]
            try:
                verified, result = future.result()
            except LLMError as exc:
                progress["failed"] += 1
                errors.append(str(exc))
                source.mining_state = {**source.mining_state, unit.number: "failed"}
                _log(db, run, f"{unit.number}절 실패: {exc}", level="error")
            else:
                stored = _store_unit(db, run, source, unit, rows, verified, result.model, position)
                position += stored
                unverified = sum(not v.verified for v in verified)
                progress["done"] += 1
                progress["input_tokens"] += result.input_tokens
                progress["output_tokens"] += result.output_tokens
                source.mining_state = {**source.mining_state, unit.number: "done"}
                note = f" (인용 미확인 {unverified}건)" if unverified else ""
                _log(db, run, f"{unit.number}절: 요건 {stored}건{note}")
            run.progress = dict(progress)
            # 절 하나가 끝날 때마다 반영해 화면에서 진행 상황이 보이게 한다.
            db.commit()

    if units and progress["done"] == 0:
        source.status = "extracted"
        _finish(db, run, "failed", errors[0] if errors else "요건을 도출하지 못했습니다.")
    else:
        source.status = "mined"
        _finish(db, run, "succeeded")
        if progress["failed"]:
            _log(
                db,
                run,
                f"{progress['failed']}개 절은 실패했습니다. 다시 도출하면 실패한 절만 처리합니다.",
            )
    db.commit()


_HANDLERS = {
    "mine_requirements": run_mining,
    "design_system": generation_jobs.run_design,
    "write_documents": generation_jobs.run_write,
    "harmonize_artifact": harmonize_jobs.run_harmonize,
}


# ── 대기열 ───────────────────────────────────────────────────────────────────


def process_next_run() -> bool:
    """대기 중인 작업 하나를 실행한다. 할 일이 없었으면 False."""
    with get_engine().begin() as conn:
        claimed = conn.execute(text("SELECT run_id, run_tenant FROM claim_next_run()")).first()
    if claimed is None:
        return False
    run_id: uuid.UUID = claimed.run_id
    tenant_id: uuid.UUID = claimed.run_tenant

    with get_sessionmaker()() as db:
        set_tenant(db, tenant_id)
        run = db.get(Run, run_id)
        try:
            _HANDLERS[run.kind](db, run)
        except Exception:
            logger.exception("작업 %s (%s) 실패", run_id, run.kind)
            db.rollback()
            run = db.get(Run, run_id)
            source = db.get(SourceDocument, run.source_id) if run.source_id else None
            if source is not None and source.status == "mining":
                source.status = "extracted"
            generation_jobs.recover_after_failure(db, run)
            _finish(db, run, "failed", "작업 중 예상하지 못한 오류가 났습니다. 다시 실행하세요.")
            db.commit()
    return True


def run_forever(stop: threading.Event) -> None:
    with get_engine().begin() as conn:
        interrupted = conn.execute(text("SELECT fail_interrupted_runs()")).scalar_one()
    if interrupted:
        logger.warning("중단된 작업 %d건을 실패로 정리했습니다.", interrupted)
    while not stop.is_set():
        try:
            if process_next_run():
                continue
        except Exception:
            logger.exception("작업자 오류")
        stop.wait(_IDLE_SECONDS)


def start_in_background() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(stop,), name="run-worker", daemon=True).start()
    return stop


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever(threading.Event())
