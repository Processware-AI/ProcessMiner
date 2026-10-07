"""개정판 상태 전이와 버전 규칙 (순수 함수).

버전 규칙(02_문서번호체계.md §버전 규칙):
  최초 승인판 1.0, 경미 개정 1.n, 구조·책임·범위 변경 {n+1}.0.
개정판의 version 은 '승인되면 될 버전'을 뜻하고, 초안 여부는 status 로 구분한다.
"""

import hashlib
import json
import re
from dataclasses import dataclass
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


# 조직이 스스로 정해야 하는 곳의 표시: 〔조직 결정: 검토 주기〕
_DECISION = re.compile(r"〔조직 결정:\s*([^〕\n]*?)\s*〕")
DECISION_PATTERN = _DECISION
_CONTEXT = 140  # 앞뒤로 보여줄 글자 수


@dataclass
class OpenDecision:
    label: str
    before: str  # 같은 줄에서 표시 앞의 글
    after: str  # 같은 줄에서 표시 뒤의 글


def find_decisions(body: str) -> list[OpenDecision]:
    """본문에 남아 있는 조직 결정 항목. 어떤 문맥인지 알 수 있게 같은 줄의 앞뒤를 함께 준다."""
    found = []
    for match in _DECISION.finditer(body):
        line_start = body.rfind("\n", 0, match.start()) + 1
        line_end = body.find("\n", match.end())
        line_end = len(body) if line_end == -1 else line_end
        before = body[line_start : match.start()]
        after = body[match.end() : line_end]
        found.append(
            OpenDecision(
                label=match.group(1),
                before=("…" + before[-_CONTEXT:]) if len(before) > _CONTEXT else before,
                after=(after[:_CONTEXT] + "…") if len(after) > _CONTEXT else after,
            )
        )
    return found


def open_decisions(sections: list[dict[str, Any]]) -> list[str]:
    """개정판에 남아 있는 조직 결정 항목의 이름(나오는 순서대로, 중복 포함)."""
    return [
        decision.label
        for section in sections
        for decision in find_decisions(section.get("body_md") or "")
    ]


def fill_decision(body: str, label: str, value: str) -> tuple[str, int]:
    """이름이 label 인 항목을 value 로 바꾼다. (바뀐 본문, 바뀐 곳 수)"""
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        if match.group(1) != label:
            return match.group(0)
        count += 1
        return value

    return _DECISION.sub(replace, body), count


def missing_required_sections(
    sections: list[dict[str, Any]], schema: list[dict[str, Any]]
) -> list[str]:
    """필수 섹션 중 본문이 빈 것의 제목 목록."""
    bodies = {s["key"]: (s.get("body_md") or "").strip() for s in sections}
    return [
        spec["title"] for spec in schema if spec.get("required") and not bodies.get(spec["key"])
    ]
