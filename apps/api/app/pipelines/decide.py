"""초안의 〔조직 결정: …〕 항목에 들어갈 값을 모델이 정한다.

표준이 값을 정하지 않은 곳(주기, 기한, 담당, 기준값 등)이다. 모델은 해당 산업에서 흔히 쓰는
합리적인 기본값을 제안하고, 같은 이름의 항목은 문맥이 같으면 같은 값을 쓴다. 정한 값은 문서에
들어가지만, 모델이 정했다는 표시와 근거가 남아 사람이 검토할 수 있다.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app import llm

PROMPT = """\
당신은 조직의 프로세스 문서를 완성하는 품질·프로세스 컨설턴트입니다.
표준에서 만든 문서 초안에는 표준이 값을 정하지 않아 조직이 스스로 정해야 하는 곳이
〔조직 결정: 무엇을 정해야 하는지〕 로 남아 있습니다. 그 자리마다 들어갈 값을 정하세요.
정한 값은 문장 안의 표시를 그대로 대체하므로, 앞뒤 문장과 이어 읽었을 때 자연스러워야 합니다.

규칙
1. 그 산업(조직과 체계 이름에서 알 수 있는 분야)에서 흔히 쓰고 심사에서 받아들여지는 합리적인
   기본값을 정합니다. 지나치게 엄격하거나 느슨하지 않게, 처음 운영하는 조직이 지킬 수 있는 값으로.
2. value 는 표시를 대신할 짧은 표현입니다. 예: "연 1회", "릴리스 후 30일 이내", "품질 책임자",
   "95% 이상", "전자문서관리시스템, 제품 수명 종료 후 10년". 문장 전체를 다시 쓰지 않습니다.
   앞뒤 글과 이어져 자연스럽도록 조사를 붙이지 않은 명사구나 짧은 구로 씁니다.
3. 특정 회사 이름, 사람 이름, 제품 이름, 도구 상품명을 지어내지 않습니다. 담당은 역할 이름으로,
   도구는 일반 명칭(예: 이슈 관리 시스템)으로 씁니다.
4. 이름이 같은 항목은 문맥이 같으면 같은 값을 씁니다. 문맥에 따라 값이 달라야 하면 다르게 씁니다
   (예: '목표 비율' 은 지표마다 다릅니다).
5. 표준이나 법규가 값을 정해 둔 것으로 알려진 항목이라도 확실하지 않으면 일반적인 값을 쓰고,
   rationale 에 확인이 필요하다고 적습니다.
6. rationale 에는 그 값을 고른 이유를 한국어 한 문장으로 적습니다.
7. id 는 주어진 것을 그대로 쓰고, 주어진 모든 항목을 한 번씩 돌려줍니다.
8. value 에 〔 〕 기호를 쓰지 않습니다.
"""


class Decided(BaseModel):
    id: str
    value: str = Field(description="표시를 대신할 짧은 값")
    rationale: str


class DecideOutput(BaseModel):
    items: list[Decided]


@dataclass
class Blank:
    """채울 자리 하나."""

    id: str
    label: str
    document: str  # "WI-QMS-01-01-01 개발 계획 수립 지침"
    section: str
    before: str
    after: str


def decide(
    blanks: list[Blank], context: str, known: dict[str, str]
) -> tuple[dict[str, Decided], llm.LLMResult[DecideOutput]]:
    """자리마다 값을 정한다. known 은 이 체계에서 이미 정한 값(일관되게 쓰도록 보여준다)."""
    lines = [f"# 조직\n{context}"]
    if known:
        lines.append(
            "# 이 체계에서 이미 정한 값(같은 문맥이면 그대로 쓰세요)\n"
            + "\n".join(f"- {label}: {value}" for label, value in list(known.items())[:80])
        )
    lines.append("# 채울 자리")
    for blank in blanks:
        lines.append(
            f"- id: {blank.id}\n  항목: {blank.label}\n  문서: {blank.document} / {blank.section}\n"
            f"  문장: {blank.before}〔{blank.label}〕{blank.after}"
        )
    result = llm.structured(
        system=PROMPT, user="\n".join(lines), schema=DecideOutput, max_tokens=16000
    )
    valid = {b.id for b in blanks}
    decided = {}
    for item in result.output.items:
        value = item.value.strip().replace("〔", "").replace("〕", "")
        if item.id in valid and value:
            decided[item.id] = item.model_copy(update={"value": value[:500]})
    return decided, result
