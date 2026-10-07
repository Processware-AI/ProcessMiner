"""양식(템플릿)마다 작성예시를 쓴다.

작성예시는 교육용 샘플이다. 실무자가 양식을 처음 채울 때 무엇을 어떻게 적어야 하는지 보여주고,
심사에서 자주 지적되는 실수를 알려준다. 실제 기록으로 쓰지 않으므로 값은 가상이고, 가상임이
드러나게 쓴다.
"""

from dataclasses import dataclass

from pydantic import BaseModel

from app import llm

PROMPT = """\
당신은 조직의 실무자를 가르치는 품질·프로세스 교육 담당자입니다.
기록 양식(템플릿) 하나와, 그 양식을 쓰는 업무지침, 지침이 이행하는 표준 요건이 주어집니다.
이 양식을 처음 채우는 실무자가 따라 할 수 있는 작성예시를 쓰세요.

작성 규칙
1. sample 섹션: 양식의 기록 항목마다 한 행씩, 주어진 순서대로 표를 만듭니다.
   | 항목 | 예시값 | 작성 요령 |
   - 예시값은 지침의 단계와 요건에 맞는 그럴듯한 값입니다. 업무가 실제로 이렇게 진행됐다고 보고
     앞뒤 항목이 서로 맞게 씁니다(번호, 날짜 순서, 버전, 결론이 일관되게).
   - 가상의 값이 드러나게 씁니다: 사람은 역할과 기호(예: 시험 담당자 A), 제품은 "제품 X v1.2",
     번호는 "RC-001" 처럼. 실제 회사·사람·제품·상품 이름을 쓰지 않습니다.
   - 작성 요령은 그 항목을 어떻게 채우는지 한두 문장으로 적습니다. 요건이 그 항목에 요구하는
     것이 있으면 함께 적습니다. 표 안에서는 줄을 바꾸지 않습니다.
2. cautions 섹션: 이 양식을 쓸 때 지킬 점을 3~6개 목록으로 적습니다(빠뜨리기 쉬운 항목,
   다른 기록과 맞춰야 하는 값, 승인 전에 확인할 것).
3. bad_examples 섹션: 심사에서 지적받기 쉬운 잘못된 작성 2~4건을, 무엇이 왜 문제인지와 함께
   적습니다. 형식: "- **잘못된 예**: … — **문제**: …"
4. 지침과 요건에 없는 수치·기한·도구 이름·규칙을 새로 정하지 않습니다. 지침에 〔조직 결정: …〕 이
   남아 있으면 예시값에는 그 자리가 조직이 정할 값이라는 것이 드러나게 "(조직이 정한 주기)"처럼
   쓰고, 작성 요령에서도 "조직이 정한 번호 체계에 따라"처럼 쓰며 규칙을 지어내지 않습니다.
5. key 는 주어진 것만 쓰고, 주어진 섹션을 모두 한 번씩 돌려줍니다.
"""


class ExampleSection(BaseModel):
    key: str
    body_md: str


class ExampleOutput(BaseModel):
    sections: list[ExampleSection]


@dataclass
class ExampleTask:
    template_title: str
    template_guide: str
    fields: list[str]
    instruction_title: str
    instruction_steps: str
    requirements: list[str]  # "IEC62304 5.1.1-01: 요약"
    section_schema: list[dict]


def write(task: ExampleTask) -> tuple[list[dict], llm.LLMResult[ExampleOutput]]:
    """작성예시 본문을 쓴다. [{key, title, body_md}] 를 섹션 구성 순서로 돌려준다."""
    parts = [
        f"# 양식: {task.template_title}",
        "기록 항목:\n" + "\n".join(f"- {name}" for name in task.fields),
    ]
    if task.template_guide.strip():
        parts.append(f"작성 안내:\n{task.template_guide.strip()}")
    parts.append(f"# 업무지침: {task.instruction_title}\n{task.instruction_steps.strip()[:6000]}")
    if task.requirements:
        parts.append("# 지침이 이행하는 요건\n" + "\n".join(f"- {r}" for r in task.requirements))
    parts.append(
        "# 섹션 구성\n"
        + "\n".join(f"- key: {s['key']} | 제목: {s['title']}" for s in task.section_schema)
    )
    result = llm.structured(
        system=PROMPT, user="\n\n".join(parts), schema=ExampleOutput, max_tokens=16000
    )
    by_key = {s.key: s.body_md.strip() for s in result.output.sections}
    sections = [
        {"key": s["key"], "title": s["title"], "body_md": by_key.get(s["key"], "")}
        for s in task.section_schema
    ]
    if not sections or not sections[0]["body_md"]:
        raise llm.LLMError("작성예시의 샘플 입력값을 만들지 못했습니다.")
    return sections, result
