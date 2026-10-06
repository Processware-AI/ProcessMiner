"""문서 번호 규칙 — tools/vault_rules/generator.py 의 순수 함수를 이식.

정본: vault/00_공통관리/02_문서번호체계.md v1.8 (모든 계층 2자리, REC 일련 3자리).
일련번호 자체는 여기서 정하지 않는다. DB 시퀀스(app.domain.numbering)가 발급한다.
"""

import re
from dataclasses import dataclass


@dataclass
class DocId:
    doc_type: str
    scope: str
    pol_seq: str | None = None  # 2자리
    pro_seq: str | None = None  # 2자리
    wi_seq: str | None = None  # 2자리
    tmp_seq: str | None = None  # 2자리
    year: str | None = None  # 4자리 (REC)
    rec_seq: str | None = None  # 3자리 (REC)
    flat_seq: str | None = None  # 3자리 (REF)

    def __str__(self) -> str:
        return build_doc_id(self)


_PATTERNS = {
    # REC-QMS-01-01-02-01-2026-001
    "REC": re.compile(
        r"^REC-(?P<scope>[A-Z]+)-(?P<pol>\d{2})-(?P<pro>\d{2})-(?P<wi>\d{2})"
        r"-(?P<tmp>\d{2})-(?P<year>\d{4})-(?P<rec>\d{3})$"
    ),
    # TMP-QMS-01-01-02-01 / EX-QMS-01-01-02-01
    "TMP": re.compile(
        r"^(?P<type>TMP|EX)-(?P<scope>[A-Z]+)-(?P<pol>\d{2})-(?P<pro>\d{2})"
        r"-(?P<wi>\d{2})-(?P<tmp>\d{2})$"
    ),
    # WI-QMS-01-01-02
    "WI": re.compile(r"^WI-(?P<scope>[A-Z]+)-(?P<pol>\d{2})-(?P<pro>\d{2})-(?P<wi>\d{2})$"),
    # PRO-QMS-01-01
    "PRO": re.compile(r"^PRO-(?P<scope>[A-Z]+)-(?P<pol>\d{2})-(?P<pro>\d{2})$"),
    # POL-QMS-01
    "POL": re.compile(r"^POL-(?P<scope>[A-Z]+)-(?P<pol>\d{2})$"),
    # REF-001
    "REF": re.compile(r"^REF-(?P<seq>\d{3})$"),
}


def parse_doc_id(raw: str) -> DocId:
    """문서 번호 문자열을 DocId 로 분해한다. 형식이 맞지 않으면 ValueError."""
    raw = raw.strip()

    if m := _PATTERNS["REC"].match(raw):
        return DocId(
            doc_type="REC",
            scope=m["scope"],
            pol_seq=m["pol"],
            pro_seq=m["pro"],
            wi_seq=m["wi"],
            tmp_seq=m["tmp"],
            year=m["year"],
            rec_seq=m["rec"],
        )
    if m := _PATTERNS["TMP"].match(raw):
        return DocId(
            doc_type=m["type"],
            scope=m["scope"],
            pol_seq=m["pol"],
            pro_seq=m["pro"],
            wi_seq=m["wi"],
            tmp_seq=m["tmp"],
        )
    if m := _PATTERNS["WI"].match(raw):
        return DocId(
            doc_type="WI", scope=m["scope"], pol_seq=m["pol"], pro_seq=m["pro"], wi_seq=m["wi"]
        )
    if m := _PATTERNS["PRO"].match(raw):
        return DocId(doc_type="PRO", scope=m["scope"], pol_seq=m["pol"], pro_seq=m["pro"])
    if m := _PATTERNS["POL"].match(raw):
        return DocId(doc_type="POL", scope=m["scope"], pol_seq=m["pol"])
    if m := _PATTERNS["REF"].match(raw):
        return DocId(doc_type="REF", scope="", flat_seq=m["seq"])

    raise ValueError(f"Cannot parse doc ID: {raw!r}")


def build_doc_id(d: DocId) -> str:
    t = d.doc_type
    if t == "POL":
        return f"POL-{d.scope}-{d.pol_seq}"
    if t == "PRO":
        return f"PRO-{d.scope}-{d.pol_seq}-{d.pro_seq}"
    if t == "WI":
        return f"WI-{d.scope}-{d.pol_seq}-{d.pro_seq}-{d.wi_seq}"
    if t in ("TMP", "EX"):
        return f"{t}-{d.scope}-{d.pol_seq}-{d.pro_seq}-{d.wi_seq}-{d.tmp_seq}"
    if t == "REC":
        return f"REC-{d.scope}-{d.pol_seq}-{d.pro_seq}-{d.wi_seq}-{d.tmp_seq}-{d.year}-{d.rec_seq}"
    if t == "REF":
        return f"REF-{d.flat_seq}"
    raise ValueError(f"Unknown doc_type: {t!r}")


def new_root_id(doc_type: str, scope: str, seq: int) -> str:
    """상위 문서가 없는 유형의 번호. POL-QMS-01, REF-001."""
    if doc_type == "POL":
        if not re.fullmatch(r"[A-Z]{2,8}", scope):
            raise ValueError(f"Invalid scope code: {scope!r}")
        _check_range(seq, 99)
        return f"POL-{scope}-{seq:02d}"
    if doc_type == "REF":
        _check_range(seq, 999)
        return f"REF-{seq:03d}"
    raise ValueError(f"{doc_type!r} is not a root document type")


def new_child_id(parent_id: str, child_type: str, seq: int, year: int | None = None) -> str:
    """상위 번호와 다음 일련번호로 하위 문서 번호를 만든다.

    POL-QMS-01 + PRO + 2      → PRO-QMS-01-02
    PRO-QMS-01-01 + WI + 3    → WI-QMS-01-01-03
    WI-QMS-01-01-03 + TMP + 1 → TMP-QMS-01-01-03-01
    """
    p = parse_doc_id(parent_id)

    if child_type == "PRO" and p.doc_type == "POL":
        _check_range(seq, 99)
        return f"PRO-{p.scope}-{p.pol_seq}-{seq:02d}"
    if child_type == "WI" and p.doc_type == "PRO":
        _check_range(seq, 99)
        return f"WI-{p.scope}-{p.pol_seq}-{p.pro_seq}-{seq:02d}"
    if child_type in ("TMP", "EX") and p.doc_type == "WI":
        _check_range(seq, 99)
        return f"{child_type}-{p.scope}-{p.pol_seq}-{p.pro_seq}-{p.wi_seq}-{seq:02d}"
    if child_type == "REC" and p.doc_type == "TMP":
        if year is None:
            raise ValueError("REC requires a year")
        _check_range(seq, 999)
        return f"REC-{p.scope}-{p.pol_seq}-{p.pro_seq}-{p.wi_seq}-{p.tmp_seq}-{year}-{seq:03d}"

    raise ValueError(f"Cannot create child {child_type!r} under parent {parent_id!r}")


def _check_range(seq: int, maximum: int) -> None:
    if not 1 <= seq <= maximum:
        raise ValueError(f"Sequence {seq} out of range 1..{maximum}")


def increment_version(current: str, change: str = "minor") -> str:
    """major → x+1.0, minor → x.y+1"""
    parts = current.lstrip("v").split(".")
    major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if change == "major":
        return f"{major + 1}.0"
    return f"{major}.{minor + 1}"


def cascade_ids(old_pol_id: str, new_pol_id: str, affected_ids: list[str]) -> dict[str, str]:
    """POL 번호가 바뀔 때 하위 문서 번호의 {이전: 이후} 매핑을 돌려준다."""
    old = parse_doc_id(old_pol_id)
    new = parse_doc_id(new_pol_id)
    if old.doc_type != "POL" or new.doc_type != "POL":
        raise ValueError("Both IDs must be POL type")

    mapping: dict[str, str] = {}
    for raw in affected_ids:
        try:
            d = parse_doc_id(raw)
        except ValueError:
            continue
        if d.pol_seq != old.pol_seq or d.scope != old.scope:
            continue
        d.pol_seq = new.pol_seq
        d.scope = new.scope
        mapping[raw] = build_doc_id(d)
    return mapping
