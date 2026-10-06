"""쪽별 본문을 조항 단위로 나눈다.

번호가 붙은 표준·법규 문서(1, 1.1, 1.1.1 … 과 Annex A, A.1 …)를 대상으로 한다.
제목처럼 보이는 줄을 모두 조항으로 받아들이면 본문 속 "5.2 and 5.3 …" 같은 문장이
끼어들므로, 번호가 직전 조항의 올바른 다음 번호일 때만 조항 제목으로 인정한다.
"""

import re
from dataclasses import dataclass, field

from .pdf import PageText

# "5.1.1 Software development plan", "4.1 * Quality management system"
_NUMBERED = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,4})\s+(\*\s*)?(\S.{0,140}?)\s*$")
# "Annex B"
_ANNEX = re.compile(r"^\s*Annex\s+([A-Z])\s*$", re.IGNORECASE)
# "B.4.2 Something"
_ANNEX_NUMBERED = re.compile(r"^\s*([A-Z](?:\.\d{1,2}){1,4})\s+(\*\s*)?(\S.{0,140}?)\s*$")
# 목차의 점선과 쪽 번호: "5.1.1 Software development plan ......... 18"
_TOC_LEADER = re.compile(r"\.{4,}|(?:\s\.){4,}")
_ANNEX_KIND = re.compile(r"\((informative|normative)\)", re.IGNORECASE)


@dataclass
class Clause:
    number: str  # "5.1.1", "B.4", "Annex B" 또는 프로세스 체계의 "SWE.1", "SWE.1.BP1"
    title: str
    kind: str  # clause | annex | process | practice
    normative: bool
    page_start: int
    page_end: int
    lines: list[str] = field(default_factory=list)
    has_guidance: bool = False  # 제목에 '*' 가 붙은 조항(부속서에 해설이 있다는 표시)

    @property
    def level(self) -> int:
        if self.kind in ("process", "practice"):
            return 1 if self.kind == "process" else 2
        return 1 if self.number.startswith("Annex") else self.number.count(".") + 1

    @property
    def parent_number(self) -> str | None:
        if self.kind == "process" or self.number.startswith("Annex"):
            return None
        if self.kind == "practice":
            return self.number.rsplit(".", 1)[0]
        if "." not in self.number:
            return None
        head = self.number.rsplit(".", 1)[0]
        # 부속서의 첫 단계(B.4)는 부속서 자체(Annex B) 아래에 둔다.
        return f"Annex {head}" if len(head) == 1 and head.isalpha() else head

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


# 작은 대문자로 조판된 낱말은 추출하면 첫 글자가 떨어져 나온다: "R ISK", "S oftware".
# 한 글자짜리 낱말로 실제 쓰이는 A 와 I, 그리고 소유격의 ’S 는 건드리지 않는다.
_SPLIT_INITIAL = re.compile(r"(?<![’'])\b([B-HJ-Z]) (?=[A-Za-z]{2,})")


def clean_title(title: str) -> str:
    """조항 제목에서 추출 과정의 흔적(떨어진 첫 글자, 겹친 공백)을 정리한다."""
    return re.sub(r"\s+", " ", _SPLIT_INITIAL.sub(r"\1", title)).strip()


def _key(number: str) -> tuple[int, ...]:
    return tuple(int(part) for part in number.split("."))


def _is_successor(previous: tuple[int, ...], candidate: tuple[int, ...]) -> bool:
    """candidate 가 previous 바로 다음에 올 수 있는 번호인가.

    하위 첫 번호(5.1 → 5.1.1)이거나, 같은 단계 또는 상위 단계에서 1 증가한 번호(5.1.3 → 5.1.4,
    5.1.9 → 5.2, 5.8.8 → 6)만 허용한다.
    """
    if candidate == previous + (1,):
        return True
    depth = len(candidate)
    return (
        depth <= len(previous)
        and candidate[:-1] == previous[: depth - 1]
        and candidate[-1] == previous[depth - 1] + 1
    )


def segment_clauses(pages: list[PageText]) -> list[Clause]:
    """문서 순서대로 조항 목록을 만든다. 조항을 하나도 찾지 못하면 빈 목록."""
    clauses: list[Clause] = []
    current: Clause | None = None
    previous_key: tuple[int, ...] | None = None  # 본문 조항 번호
    annex_letter: str | None = None
    annex_key: tuple[int, ...] | None = None  # 부속서 안의 번호(문자 제외)
    annex_normative = False

    def start(clause: Clause) -> None:
        nonlocal current
        clauses.append(clause)
        current = clause

    for page in pages:
        lines = page.text.splitlines()
        for index, line in enumerate(lines):
            if _TOC_LEADER.search(line):
                continue  # 목차 줄은 조항도 본문도 아니다

            annex = _ANNEX.match(line)
            if annex and previous_key is not None:
                annex_letter = annex.group(1).upper()
                annex_key = None
                following = " ".join(lines[index + 1 : index + 4])
                kind = _ANNEX_KIND.search(following)
                annex_normative = bool(kind and kind.group(1).lower() == "normative")
                start(
                    Clause(
                        number=f"Annex {annex_letter}",
                        title="",
                        kind="annex",
                        normative=annex_normative,
                        page_start=page.page_no,
                        page_end=page.page_no,
                    )
                )
                continue

            if annex_letter is not None:
                numbered = _ANNEX_NUMBERED.match(line)
                if numbered and numbered.group(1).startswith(f"{annex_letter}."):
                    key = _key(numbered.group(1)[2:])
                    if (annex_key is None and key == (1,)) or (
                        annex_key is not None and _is_successor(annex_key, key)
                    ):
                        annex_key = key
                        start(
                            Clause(
                                number=numbered.group(1),
                                title=clean_title(numbered.group(3)),
                                kind="annex",
                                normative=annex_normative,
                                page_start=page.page_no,
                                page_end=page.page_no,
                                has_guidance=bool(numbered.group(2)),
                            )
                        )
                        continue
            else:
                numbered = _NUMBERED.match(line)
                if numbered:
                    key = _key(numbered.group(1))
                    # 1 번 조항이 다시 나오면, 앞서 모은 것이 진짜 본문이 아니었는지 본다.
                    # 목차였거나(조항마다 본문이 거의 없다), 서문의 각주 "1 …" 한 줄을
                    # 1 번 조항으로 잘못 잡은 경우(뒤따르는 조항이 하나도 없다)다.
                    restart = (
                        key == (1,)
                        and previous_key is not None
                        and (not current_has_body(clauses) or len(clauses) == 1)
                    )
                    if previous_key is None and key != (1,):
                        pass  # 첫 조항(1)이 나오기 전의 번호는 무시한다
                    elif previous_key is None or restart or _is_successor(previous_key, key):
                        if restart:
                            clauses.clear()  # 앞서 모은 것은 목차였다
                        previous_key = key
                        start(
                            Clause(
                                number=numbered.group(1),
                                title=clean_title(numbered.group(3)),
                                kind="clause",
                                normative=True,
                                page_start=page.page_no,
                                page_end=page.page_no,
                                has_guidance=bool(numbered.group(2)),
                            )
                        )
                        continue

            if current is not None:
                current.lines.append(line)
                current.page_end = page.page_no

    # 부속서 첫 줄들에 있는 "(informative)" 와 제목을 부속서 제목으로 옮긴다.
    for clause in clauses:
        if clause.number.startswith("Annex") and not clause.title:
            head = [line.strip() for line in clause.lines[:4] if line.strip()]
            title = [line for line in head if not _ANNEX_KIND.fullmatch(line)]
            clause.title = clean_title(title[0]) if title else ""
    return clauses


# ── 프로세스 체계(조항 번호 대신 프로세스 ID 를 쓰는 문서) ────────────────────
#
# Automotive SPICE 같은 프로세스 평가 모델은 "SWE.1 Software Requirements Analysis" 처럼
# 프로세스 ID 로 나뉘고, 요구사항에 해당하는 것은 기본 프랙티스(SWE.1.BP1)와 프로세스 결과다.
# 장 번호가 앞에 붙은 제목("4.4.1 SWE.1 …")도 같은 프로세스로 본다.

_PROCESS = re.compile(
    r"^\s*(?:\d{1,2}(?:\.\d{1,2}){0,4}\s+)?([A-Z]{2,4}\.\d{1,2})\s+(\S.{0,140}?)\s*$"
)
_PRACTICE = re.compile(r"^\s*([A-Z]{2,4}\.\d{1,2}\.BP\d{1,2})\s*[:.\-–]?\s*(\S.{0,200}?)?\s*$")
_MIN_PROCESSES = 3


def segment_processes(pages: list[PageText]) -> list[Clause]:
    """프로세스 ID 로 나눈다. 기본 프랙티스가 딸린 프로세스가 셋 미만이면 빈 목록."""
    clauses: list[Clause] = []
    current: Clause | None = None
    process: str | None = None
    for page in pages:
        for line in page.text.splitlines():
            if _TOC_LEADER.search(line):
                continue
            practice = _PRACTICE.match(line)
            if practice and process and practice.group(1).startswith(process + "."):
                current = Clause(
                    number=practice.group(1),
                    title=clean_title(practice.group(2) or ""),
                    kind="practice",
                    normative=True,
                    page_start=page.page_no,
                    page_end=page.page_no,
                    lines=[line.strip()],
                )
                clauses.append(current)
                continue
            heading = _PROCESS.match(line)
            # 본문 속에서 프로세스를 가리키는 줄("SWE.1 and SWE.2 …")은 제목이 아니다.
            if heading and not re.match(r"^(and|or|to|of|for|in)\b", heading.group(2), re.I):
                if heading.group(1) != process:
                    process = heading.group(1)
                    current = Clause(
                        number=process,
                        title=clean_title(heading.group(2)),
                        kind="process",
                        normative=True,
                        page_start=page.page_no,
                        page_end=page.page_no,
                    )
                    clauses.append(current)
                    continue
            if current is not None:
                current.lines.append(line)
                current.page_end = page.page_no

    with_practices = {c.number.rsplit(".", 1)[0] for c in clauses if c.kind == "practice"}
    clauses = [c for c in clauses if c.kind == "practice" or c.number in with_practices]
    if len(with_practices) < _MIN_PROCESSES:
        return []
    # 같은 프로세스가 목차·본문에 두 번 나오면 본문(뒤의 것)을 쓴다.
    seen: dict[str, int] = {}
    for index, clause in enumerate(clauses):
        seen[clause.number] = index
    return [c for i, c in enumerate(clauses) if seen[c.number] == i]


def segment(pages: list[PageText]) -> list[Clause]:
    """문서의 짜임에 맞는 방식으로 나눈다. 프로세스 ID 체계가 뚜렷하면 그것을 쓴다."""
    processes = segment_processes(pages)
    if processes:
        return processes
    return segment_clauses(pages)


def current_has_body(clauses: list[Clause]) -> bool:
    """지금까지 모은 조항에 본문이 있는가. 목차만 훑었다면 조항마다 본문이 거의 없다."""
    if not clauses:
        return False
    body_chars = sum(len(clause.text) for clause in clauses)
    return body_chars / len(clauses) > 80
