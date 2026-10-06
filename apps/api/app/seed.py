"""플랫폼 참조 데이터 적재 — seed/*.yaml → 참조 테이블.

참조 테이블은 애플리케이션 역할이 쓸 수 없으므로 소유자 역할로 접속해 실행한다.
여러 번 실행해도 결과가 같다(있으면 갱신, 없으면 추가).
"""

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.doc_types import DOC_TYPES, PARENT_TYPE
from app.models import DocTypeDef, ScopeCode, StandardDef


def _load(seed_dir: Path, name: str) -> list[dict]:
    with open(seed_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_reference_data(db: Session, seed_dir: Path) -> dict[str, int]:
    doc_types = _load(seed_dir, "doc_types.yaml")
    codes = [d["code"] for d in doc_types]
    if sorted(codes) != sorted(DOC_TYPES):
        raise ValueError(f"doc_types.yaml 의 유형 {codes} 이 코드의 유형 {DOC_TYPES} 과 다릅니다.")
    for item in doc_types:
        if item.get("parent_type") != PARENT_TYPE.get(item["code"]):
            raise ValueError(f"{item['code']} 의 상위 유형이 코드의 계층 규칙과 다릅니다.")
        row = db.get(DocTypeDef, item["code"]) or DocTypeDef(code=item["code"])
        row.name = item["name"]
        row.description = item.get("description", "")
        row.parent_type = item.get("parent_type")
        row.sort = item.get("sort", 0)
        row.sections = [
            {
                "key": s["key"],
                "title": s["title"],
                "required": bool(s.get("required", False)),
                "hint": s.get("hint", ""),
                "template": s.get("template", ""),
                "normative": bool(s.get("normative", False)),
            }
            for s in item["sections"]
        ]
        db.add(row)

    scope_codes = _load(seed_dir, "scope_codes.yaml")
    for item in scope_codes:
        row = db.scalar(
            select(ScopeCode).where(ScopeCode.tenant_id.is_(None), ScopeCode.code == item["code"])
        ) or ScopeCode(tenant_id=None, code=item["code"])
        row.name = item["name"]
        row.layer = item.get("layer")
        db.add(row)

    standards = _load(seed_dir, "standards.yaml")
    for item in standards:
        row = db.get(StandardDef, item["code"]) or StandardDef(code=item["code"])
        row.name = item["name"]
        row.layer = item["layer"]
        row.structure = item["structure"]
        row.integration_mode = item["integration_mode"]
        row.scope_codes = item.get("scope_codes", [])
        row.notes = item.get("notes", "")
        db.add(row)

    db.flush()
    return {
        "doc_types": len(doc_types),
        "scope_codes": len(scope_codes),
        "standards": len(standards),
    }
