"""산출물 정합화 작업. 작업자(app.worker)가 부른다.

한 작업이 두 단계를 한다. match: 어느 양식의 기록인지 찾는다. normalize: 양식의 항목에 원본의
값을 옮긴다. match 에서 일치도가 충분히 높으면 normalize 까지 이어서 하고, 애매하면 사람의
확정을 기다린다(확정하면 normalize 작업이 따로 들어온다).
"""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.llm import LLMError
from app.models import Artifact, ProcessSystem, Run, RunEvent
from app.pipelines import harmonize
from app.services import artifacts as artifact_svc


def _log(db: Session, run: Run, message: str, level: str = "info") -> None:
    db.add(RunEvent(tenant_id=run.tenant_id, run_id=run.id, level=level, message=message))


def _finish(db: Session, run: Run, status: str, error: str = "") -> None:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)


def _add_tokens(run: Run, result) -> None:
    progress = dict(run.progress)
    progress["input_tokens"] = progress.get("input_tokens", 0) + result.input_tokens
    progress["output_tokens"] = progress.get("output_tokens", 0) + result.output_tokens
    run.progress = progress


def run_harmonize(db: Session, run: Run) -> None:
    artifact = db.get(Artifact, run.artifact_id)
    system = db.get(ProcessSystem, artifact.system_id)
    segments = artifact_svc.segments(db, artifact.id)
    forms = artifact_svc.templates(db, system)
    step = run.progress.get("step", "match")

    try:
        if step == "match":
            if not forms:
                _finish(db, run, "failed", "이 체계에 기록 양식(템플릿)이 없습니다.")
                db.commit()
                return
            _log(db, run, f"양식 {len(forms)}개 가운데 알맞은 것을 찾습니다")
            db.commit()
            briefs = [
                harmonize.TemplateBrief(f.doc.code, f.doc.title, f.instruction, f.fields)
                for f in forms
            ]
            matched = harmonize.match(artifact.filename, segments, briefs)
            _add_tokens(run, matched)
            by_code = {f.doc.code: f for f in forms}
            artifact.candidates = [
                {
                    "document_id": str(by_code[c.code].doc.id),
                    "code": c.code,
                    "title": by_code[c.code].doc.title,
                    "confidence": c.confidence,
                    "reason": c.reason.strip(),
                }
                for c in matched.output.candidates
            ]
            if matched.output.title.strip():
                artifact.title = matched.output.title.strip()[:300]
            if matched.output.performed_on:
                try:
                    artifact.performed_on = date.fromisoformat(matched.output.performed_on)
                except ValueError:
                    pass
            best = artifact.candidates[0] if artifact.candidates else None
            if best is None or best["confidence"] < harmonize.REVIEW_THRESHOLD:
                artifact.match_state = "none"
                artifact.template_document_id = None
                artifact.match_confidence = best["confidence"] if best else None
                _log(db, run, "알맞은 양식을 찾지 못했습니다. 양식을 직접 고르세요.")
                _finish(db, run, "succeeded")
                db.commit()
                return
            artifact.match_state = "proposed"
            artifact.template_document_id = by_code[best["code"]].doc.id
            artifact.match_confidence = best["confidence"]
            _log(
                db, run, f"양식 제안: {best['code']} {best['title']} (일치도 {best['confidence']})"
            )
            if best["confidence"] < harmonize.AUTO_THRESHOLD:
                _log(db, run, "일치도가 높지 않습니다. 양식을 확인한 뒤 진행하세요.")
                _finish(db, run, "succeeded")
                db.commit()
                return
            db.commit()

        chosen = next((f for f in forms if f.doc.id == artifact.template_document_id), None)
        if chosen is None:
            _finish(db, run, "failed", "양식을 찾을 수 없습니다. 양식을 다시 고르세요.")
            db.commit()
            return
        if not chosen.fields:
            _finish(db, run, "failed", "양식에 기록 항목이 없습니다. 양식 문서를 확인하세요.")
            db.commit()
            return
        _log(db, run, f"{chosen.doc.title} 양식의 항목 {len(chosen.fields)}개에 값을 옮깁니다")
        db.commit()
        guide = next(
            (s.get("body_md") or "" for s in chosen.revision.sections if s.get("key") == "guide"),
            "",
        )
        values, result, truncated = harmonize.normalize(
            chosen.doc.title, guide, chosen.fields, segments
        )
        _add_tokens(run, result)
        artifact_svc.save_draft(
            db,
            artifact=artifact,
            chosen=chosen,
            values=values,
            model=result.model,
            actor_id=run.started_by,
        )
        filled = sum(bool(v.value) for v in values)
        unverified = sum(bool(v.value) and not v.verified for v in values)
        _log(
            db,
            run,
            f"항목 {len(values)}개 가운데 {filled}개를 원본에서 채웠습니다"
            + (f" (원본과 대조되지 않은 값 {unverified}개)" if unverified else ""),
        )
        if truncated:
            _log(db, run, "문서가 길어 앞부분만 읽었습니다. 빠진 값이 있을 수 있습니다.", "error")
        _finish(db, run, "succeeded")
    except LLMError as exc:
        _finish(db, run, "failed", str(exc))
    db.commit()
