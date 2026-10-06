"""조항 본문에서 요건을 도출한다.

모델이 하는 일은 '어느 문장이 요건인지 가려내고 요약하는 것' 뿐이다.
요건의 원문은 모델이 조항에서 그대로 옮겨 적게 하고, 실제로 그 조항에 있는 문장인지는
코드가 대조한다. 대조되지 않는 요건은 근거 없음으로 표시되어 확정 대상에서 빠진다.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.extract.structure import Clause

_OBLIGATION_WORDS = re.compile(r"\b(shall|should|may)\b|하여야|해야|할 수 있", re.IGNORECASE)

SYSTEM_PROMPT = """\
당신은 표준·법규 문서에서 요구사항을 뽑아내는 분석가입니다. 결과는 조직의 프로세스 문서를
만드는 근거가 되고, 인증 심사에서 "이 절차는 표준의 어느 문장에서 나왔는가"를 증명하는 데 쓰입니다.
그래서 정확한 인용이 가장 중요합니다.

입력으로 한 절의 조항들이 번호와 함께 주어집니다. 다음 규칙으로 요구사항을 뽑으세요.

1. 요구사항은 문서가 누군가에게 의무·권고·허용을 부과하는 문장입니다(shall, should, may 등).
   정의, 배경 설명, NOTE, 예시는 요구사항이 아닙니다.
2. 의무 하나가 요구사항 하나입니다. 한 조항에 독립된 의무가 여럿이면 나눕니다.
   하나의 의무에 딸린 나열 항목(a, b, c …)은 나누지 않고 그 의무에 함께 둡니다.
3. quote 에는 그 요구사항의 원문을 조항에서 한 글자도 바꾸지 말고 그대로 옮깁니다.
   이어진 한 구간이어야 하며, 줄임표를 쓰거나 문장을 다듬거나 번역하지 않습니다.
   원문에 띄어쓰기가 어색하게 들어가 있어도(추출 과정의 흔적) 그대로 둡니다.
   나열 항목이 딸려 있으면 그 항목들까지 포함합니다.
4. clause 에는 그 문장이 실제로 들어 있는 조항 번호를 적습니다.
5. summary 는 한국어 한두 문장으로, 누가 무엇을 해야 하는지를 원문에 있는 내용만으로 씁니다.
   원문에 없는 방법·기준·예시를 보태지 않습니다.
6. applicability 에는 원문이 적용 범위를 밝힌 표기(예: "Class A, B, C")가 있으면 그대로 적고,
   없으면 빈 문자열로 둡니다.
7. evidence 에는 이 요구사항을 지켰음을 보여줄 산출물·기록을 한국어 명사구로 적습니다.
   원문이 직접 언급하거나 요구사항에서 바로 따라 나오는 것만 적고, 없으면 비웁니다.

요구사항이 하나도 없는 절이면 빈 목록을 돌려주세요.
"""


class MinedRequirement(BaseModel):
    clause: str = Field(description="요구사항이 들어 있는 조항 번호. 예: 5.1.1")
    quote: str = Field(description="조항에서 그대로 옮긴 원문")
    obligation: Literal["shall", "should", "may"]
    summary: str = Field(description="한국어 요약")
    category: Literal["process", "documentation", "verification", "record", "other"] = Field(
        description="process: 활동 수행, documentation: 계획·문서 작성, verification: 검증·검토, "
        "record: 기록 유지, other: 그 밖"
    )
    applicability: str
    evidence: list[str]


class MiningOutput(BaseModel):
    requirements: list[MinedRequirement]


@dataclass
class MiningUnit:
    """한 번의 모델 호출로 처리하는 조항 묶음(한 절과 그 하위 조항)."""

    number: str
    clauses: list[Clause]

    def prompt(self) -> str:
        parts = []
        for clause in self.clauses:
            parts.append(f"### {clause.number} {clause.title}\n{clause.text}".rstrip())
        return "\n\n".join(parts)


@dataclass
class VerifiedRequirement:
    mined: MinedRequirement
    clause_number: str | None  # 인용이 실제로 확인된 조항. 확인되지 않았으면 None
    page_no: int | None
    verified: bool


def has_obligation(clause: Clause) -> bool:
    return bool(_OBLIGATION_WORDS.search(clause.text))


def build_units(clauses: list[Clause], unit_level: int = 2) -> list[MiningUnit]:
    """규범 조항을 절 단위로 묶는다. 의무 표현이 하나도 없는 묶음은 뺀다."""
    units: dict[str, MiningUnit] = {}
    for clause in clauses:
        if clause.kind != "clause" or not clause.normative:
            continue
        parts = clause.number.split(".")
        key = ".".join(parts[:unit_level])
        units.setdefault(key, MiningUnit(number=key, clauses=[])).clauses.append(clause)
    return [u for u in units.values() if any(has_obligation(c) for c in u.clauses)]


def _squash(text: str) -> str:
    """대조용 정규화: 공백을 모두 없애고 소문자로. 추출 과정에서 생긴 띄어쓰기 차이를 무시한다."""
    return re.sub(r"\s+", "", text).lower()


def locate_quote(quote: str, clause: Clause) -> bool:
    squashed = _squash(quote)
    return len(squashed) >= 12 and squashed in _squash(clause.text)


def verify(unit: MiningUnit, output: MiningOutput) -> list[VerifiedRequirement]:
    """모델이 옮겨 적은 원문이 실제로 조항에 있는지 대조한다."""
    by_number = {clause.number: clause for clause in unit.clauses}
    results = []
    for mined in output.requirements:
        named = by_number.get(mined.clause.strip())
        found = named if named and locate_quote(mined.quote, named) else None
        if found is None:
            # 조항 번호를 잘못 적었을 수 있으니 같은 묶음의 다른 조항에서도 찾아본다.
            found = next((c for c in unit.clauses if locate_quote(mined.quote, c)), None)
        results.append(
            VerifiedRequirement(
                mined=mined,
                clause_number=found.number if found else None,
                page_no=found.page_start if found else None,
                verified=found is not None,
            )
        )
    return results


def mine_unit(unit: MiningUnit) -> tuple[list[VerifiedRequirement], llm.LLMResult[MiningOutput]]:
    result = llm.structured(system=SYSTEM_PROMPT, user=unit.prompt(), schema=MiningOutput)
    return verify(unit, result.output), result
