"""개정판 상태 전이와 버전 규칙 (순수 함수).

버전 규칙(02_문서번호체계.md §버전 규칙):
  최초 승인판 1.0, 경미 개정 1.n, 구조·책임·범위 변경 {n+1}.0.
개정판의 version 은 '승인되면 될 버전'을 뜻하고, 초안 여부는 status 로 구분한다.
"""

import hashlib
import json
from typing import Any

from .doc_ids import increment_version

DRAFT = "draft"
IN_REVIEW = "in_review"
APPROVED = "approved"
SUPERSEDED = "superseded"

OPEN_STATUSES = (DRAFT, IN_REVIEW)

# (현재 상태, 행위) → 다음 상태
_TRANSITIONS: dict[tuple[str, str], str] = {
    (DRAFT, "submit"): IN_REVIEW,
    (IN_REVIEW, "approve"): APPROVED,
    (IN_REVIEW, "reject"): DRAFT,
    (IN_REVIEW, "withdraw"): DRAFT,
    (APPROVED, "supersede"): SUPERSEDED,
}


class InvalidTransition(ValueError):
    pass


def next_status(current: str, action: str) -> str:
    try:
        return _TRANSITIONS[(current, action)]
    except KeyError:
        raise InvalidTransition(f"'{action}' is not allowed from status '{current}'") from None


def target_version(approved_version: str | None, change_kind: str) -> str:
    """새 초안이 승인되면 갖게 될 버전."""
    if approved_version is None:
        return "1.0"
    if change_kind not in ("minor", "major"):
        raise ValueError(f"Unknown change kind: {change_kind!r}")
    return increment_version(approved_version, change_kind)


def content_hash(title: str, sections: list[dict[str, Any]], structured: dict[str, Any]) -> str:
    """개정판 내용의 지문. 승인 시점에 고정해 이후 변조 여부를 확인하는 데 쓴다."""
    canonical = json.dumps(
        {"title": title, "sections": sections, "structured": structured},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def missing_required_sections(
    sections: list[dict[str, Any]], schema: list[dict[str, Any]]
) -> list[str]:
    """필수 섹션 중 본문이 빈 것의 제목 목록."""
    bodies = {s["key"]: (s.get("body_md") or "").strip() for s in sections}
    return [
        spec["title"] for spec in schema if spec.get("required") and not bodies.get(spec["key"])
    ]
