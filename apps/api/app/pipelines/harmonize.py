"""기존 산출물을 표준 양식의 기록으로 옮긴다: 어느 양식의 기록인지 찾고, 항목 값을 뽑는다.

모델이 하는 일은 두 가지 판단이다. (1) 이 산출물이 어느 양식(템플릿)의 기록에 해당하는지,
(2) 양식의 각 항목에 해당하는 값이 원본의 어디에 있는지. 값은 원본에 있는 것만 옮기고,
그 값이 실제로 원본의 그 자리에 있는지는 코드가 대조한다. 대조되지 않은 값은
'미검증 제안'으로 남아 사람이 확인하기 전에는 기록으로 발행할 수 없다.
원본에 없는 항목은 비워 둔다(지어내지 않는다). 사람이 보완한다.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app import llm
from app.extract.artifact import Segment

# 일치도 기준(기존 backfill-matcher 의 임계값을 계승한다)
AUTO_THRESHOLD = 75  # 이상이면 바로 항목 값까지 뽑는다(그래도 사람이 확인한다)
REVIEW_THRESHOLD = 50  # 미만이면 맞는 양식이 없다고 본다

_HEAD_CHARS = 6_000  # 양식을 찾을 때 보여주는 산출물 앞부분
_BODY_CHARS = 120_000  # 항목 값을 뽑을 때 보여주는 본문 상한


def template_fields(sections: list[dict]) -> list[str]:
    """양식의 '기록 항목' 표에서 항목 이름을 순서대로 뽑는다."""
    body = next((s.get("body_md") or "" for s in sections if s.get("key") == "fields"), "")
    names: list[str] = []
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        name = cells[0] if cells else ""
        if not name or set(name) <= set("-: ") or (not names and name == "항목"):
            continue  # 구분선, 머리글
        if name not in names:
            names.append(name)
    return names


# ── 양식 찾기 ────────────────────────────────────────────────────────────────

MATCH_PROMPT = """\
당신은 조직의 기존 문서를 표준 프로세스의 기록 양식에 맞춰 정리하는 품질 담당자입니다.
기존 산출물 한 건의 앞부분과, 조직이 쓰는 기록 양식의 목록이 주어집니다. 이 산출물이 어느
양식의 기록에 해당하는지 판단하세요. 결과는 사람이 확인합니다.

판단 규칙
1. 산출물이 실제로 담고 있는 내용(무엇을 수행하고 남긴 기록인가)을 기준으로 고릅니다.
   파일 이름이나 제목의 낱말이 비슷하다는 것만으로 고르지 않습니다.
2. 후보는 가장 알맞은 것부터 최대 3개. 알맞은 양식이 없으면 빈 목록을 돌려줍니다.
   억지로 고르지 않습니다.
3. confidence 는 0~100. 그 양식의 항목 대부분을 이 산출물로 채울 수 있으면 높게,
   주제만 비슷하고 기록의 성격이 다르면 낮게 줍니다.
   75 이상: 같은 종류의 기록이다. 50~74: 관련은 있으나 사람이 확인해야 한다. 50 미만: 다르다.
4. reason 은 한국어 한 문장으로, 무엇을 보고 그렇게 판단했는지 적습니다.
5. code 는 양식 목록에 있는 번호를 그대로 적습니다.
6. title 은 이 산출물을 가리키는 짧은 제목(문서에 적힌 제목이 있으면 그것).
7. performed_on 은 이 기록의 업무를 수행한 날짜를 YYYY-MM-DD 로. 문서에 적혀 있을 때만 적고,
   없으면 빈 문자열로 둡니다. 추측하지 않습니다.
"""


class MatchCandidate(BaseModel):
    code: str = Field(description="양식 번호. 예: TMP-QMS-01-01-01-01")
    confidence: int = Field(ge=0, le=100)
    reason: str


class MatchOutput(BaseModel):
    title: str
    performed_on: str = Field(description="YYYY-MM-DD 또는 빈 문자열")
    candidates: list[MatchCandidate]


@dataclass
class TemplateBrief:
    code: str
    title: str
    instruction: str  # 상위 지침의 제목
    fields: list[str]


def _head(segments: list[Segment], limit: int) -> tuple[str, bool]:
    parts, used = [], 0
    for segment in segments:
        piece = f"[{segment.loc}] {segment.text}"
        if used + len(piece) > limit:
            parts.append(piece[: max(0, limit - used)])
            return "\n".join(parts), True
        parts.append(piece)
        used += len(piece) + 1
    return "\n".join(parts), False


def match(
    filename: str, segments: list[Segment], templates: list[TemplateBrief]
) -> llm.LLMResult[MatchOutput]:
    """산출물에 맞는 양식 후보를 찾는다. 목록에 없는 번호와 중복은 버린다."""
    listing = "\n".join(
        f"- {t.code} | {t.title} | 지침: {t.instruction} | 항목: {', '.join(t.fields[:12])}"
        for t in templates
    )
    head, _ = _head(segments, _HEAD_CHARS)
    result = llm.structured(
        system=MATCH_PROMPT,
        user=f"# 기록 양식 목록\n{listing}\n\n# 산출물\n파일 이름: {filename}\n\n{head}",
        schema=MatchOutput,
        max_tokens=4000,
    )
    known = {t.code for t in templates}
    seen: set[str] = set()
    kept = []
    for candidate in sorted(result.output.candidates, key=lambda c: -c.confidence):
        code = candidate.code.strip()
        if code in known and code not in seen:
            seen.add(code)
            kept.append(candidate.model_copy(update={"code": code}))
    result.output.candidates = kept[:3]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", result.output.performed_on.strip()):
        result.output.performed_on = ""
    return result


# ── 항목 값 뽑기 ─────────────────────────────────────────────────────────────

NORMALIZE_PROMPT = """\
당신은 조직의 기존 문서를 표준 양식의 기록으로 옮겨 적는 품질 담당자입니다.
기록 양식의 항목 목록과, 기존 산출물의 본문이 위치 표시([3쪽], [문단 12] 등)와 함께 주어집니다.
양식의 각 항목에 해당하는 값을 산출물에서 찾아 옮기세요. 이 기록은 인증 심사에서 증적으로
쓰이고, 값마다 "원본의 어디에 그렇게 적혀 있는가"를 확인합니다. 그래서 원본에 있는 그대로가
가장 중요합니다.

규칙
1. 원본에 실제로 적혀 있는 내용만 옮깁니다. 원본에 없는 항목은 value 를 빈 문자열로 둡니다.
   짐작하거나, 그럴듯한 값을 지어내거나, 다른 항목의 값을 돌려쓰지 않습니다.
2. value 는 그 항목에 들어갈 값입니다. 원본의 표현을 살려 간결하게 적습니다. 여러 곳에 흩어진
   내용은 한 값으로 모아도 됩니다. 원본이 다른 언어면 한국어로 옮기되 고유명사·식별자는
   그대로 둡니다.
3. quote 에는 그 값의 근거가 되는 원본 구절을 한 글자도 바꾸지 말고 그대로 옮깁니다.
   이어진 한 구간이어야 하고, 줄이거나 다듬지 않습니다. 값이 여러 곳에서 왔으면 가장 핵심인 한 곳.
4. location 에는 그 구절이 있는 위치 표시를 대괄호 없이 그대로 적습니다(예: 3쪽).
5. name 은 주어진 항목 이름을 그대로 적고, 주어진 모든 항목을 한 번씩 돌려줍니다.
6. 양식에 맞지 않는 내용은 버립니다. 항목을 새로 만들지 않습니다.
"""


class ExtractedField(BaseModel):
    name: str
    value: str
    quote: str
    location: str


class NormalizeOutput(BaseModel):
    fields: list[ExtractedField]


@dataclass
class FieldValue:
    name: str
    value: str
    quote: str
    location: str
    verified: bool  # quote 가 실제로 원본에 있는가


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def locate(quote: str, location: str, segments: list[Segment]) -> str | None:
    """구절이 실제로 있는 조각의 위치. 모델이 적은 위치를 먼저 보고, 없으면 전체에서 찾는다."""
    needle = _squash(quote)
    if len(needle) < 2:
        return None
    named = [s for s in segments if s.loc == location.strip().strip("[]")]
    for segment in [*named, *segments]:
        if needle in _squash(segment.text):
            return segment.loc
    return None


def check(fields: list[str], output: NormalizeOutput, segments: list[Segment]) -> list[FieldValue]:
    """모델의 답을 양식 항목 순서로 맞추고, 값의 근거가 원본에 있는지 대조한다."""
    by_name = {f.name.strip(): f for f in output.fields}
    values = []
    for name in fields:
        found = by_name.get(name)
        value = found.value.strip() if found else ""
        if not value:
            values.append(FieldValue(name, "", "", "", verified=False))
            continue
        location = locate(found.quote, found.location, segments)
        values.append(
            FieldValue(
                name,
                value,
                found.quote.strip(),
                location or found.location.strip().strip("[]"),
                verified=location is not None,
            )
        )
    return values


def normalize(
    template_title: str, guide: str, fields: list[str], segments: list[Segment]
) -> tuple[list[FieldValue], llm.LLMResult[NormalizeOutput], bool]:
    """(항목 값, 모델 결과, 본문이 길어 잘렸는지)"""
    body, truncated = _head(segments, _BODY_CHARS)
    parts = [f"# 기록 양식: {template_title}"]
    if guide.strip():
        parts.append(f"작성 안내:\n{guide.strip()}")
    parts.append("항목:\n" + "\n".join(f"- {name}" for name in fields))
    parts.append(f"# 산출물 본문\n{body}")
    result = llm.structured(
        system=NORMALIZE_PROMPT, user="\n\n".join(parts), schema=NormalizeOutput, max_tokens=16000
    )
    return check(fields, result.output, segments), result, truncated
