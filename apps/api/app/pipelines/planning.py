"""적용요건에서 문서 체계를 만든다: 구조 설계 → 문서 작성.

모델이 하는 일은 두 가지 판단이다. (1) 어떤 문서들로 나누고 어느 요건을 어디에 둘지,
(2) 각 문서의 본문. 그 밖의 것은 코드가 한다: 모든 적용요건이 어딘가에 배정됐는지,
본문의 각 섹션이 실제로 그 문서에 배정된 요건을 근거로 댔는지. 근거가 맞지 않는 문서는
저장하지 않는다(근거 게이트).
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app import llm

# ── 구조 설계 ────────────────────────────────────────────────────────────────

DESIGN_PROMPT = """\
당신은 조직의 프로세스 문서 체계를 설계하는 품질·프로세스 컨설턴트입니다.
표준에서 뽑아 조직이 승인한 '적용요건' 목록이 주어집니다. 이 요건들을 조직이 실제로 운영할
문서 체계로 묶어 주세요. 결과는 사람이 검토한 뒤 문서 작성에 쓰입니다.

문서 유형은 네 단계입니다.
- 정책서: 조직의 원칙과 방침, 책임. 체계 전체에 1~3개면 충분합니다.
- 절차서: 정책 아래에서 하나의 업무 흐름(누가 어떤 순서로)을 다룹니다.
- 업무지침서: 절차의 한 활동을 실무자가 따라 할 수 있게 단계별로 풉니다.
- 템플릿: 지침을 수행한 결과를 남기는 기록 양식입니다.

설계 규칙
1. 모든 적용요건을 빠짐없이 하나 이상의 문서에 배정합니다. 요건은 그것을 실제로 이행하는
   가장 구체적인 문서에 둡니다. 수행 방법에 관한 요건은 업무지침서, 흐름·책임에 관한 요건은
   절차서, 방침 수준의 요건은 정책서입니다. 같은 요건을 여러 문서에 중복 배정하지 않습니다.
2. 표준의 조항 구조를 그대로 옮기지 말고, 조직에서 함께 수행되는 일끼리 묶습니다.
   다만 서로 다른 업무를 억지로 한 문서에 합치지도 않습니다.
3. 문서 수는 조직이 유지할 수 있는 만큼만 둡니다. 요건 하나에 문서 하나씩 만들지 않습니다.
   업무지침서 하나는 보통 요건 3~10개를 다룹니다.
4. 템플릿은 그 지침의 요건이 요구하는 기록·산출물에 맞춰 0~3개를 둡니다. 요건의 증적 후보를
   참고하고, 기록이 필요 없는 지침에는 두지 않습니다.
5. 제목은 한국어로, 문서 유형이 드러나게 짓습니다(… 정책, … 절차, … 지침, 양식은 … 서·표·기록).
6. purpose 는 그 문서가 다루는 범위를 한 문장으로 적습니다.
7. requirements 에는 입력에 있는 요건 코드만 그대로 적습니다. 코드를 지어내지 않습니다.
"""

PLACEMENT_PROMPT = """\
문서 체계 설계안에서 일부 적용요건이 어느 문서에도 배정되지 않았습니다.
아래의 문서 목록과 배정되지 않은 요건을 보고, 요건마다 그것을 이행하기에 가장 알맞은 문서를
하나 골라 주세요. document 에는 문서 목록에 있는 경로(예: p0.r1.w2)를 그대로 적습니다.
새 문서를 만들지 않습니다.
"""


class PlannedInstruction(BaseModel):
    title: str
    purpose: str
    requirements: list[str] = Field(description="이 지침이 이행하는 요건 코드")
    templates: list[str] = Field(description="기록 양식 제목. 없으면 빈 목록")


class PlannedProcedure(BaseModel):
    title: str
    purpose: str
    requirements: list[str] = Field(description="절차 수준에서 이행하는 요건 코드")
    instructions: list[PlannedInstruction]


class PlannedPolicy(BaseModel):
    title: str
    purpose: str
    requirements: list[str] = Field(description="방침 수준에서 이행하는 요건 코드")
    procedures: list[PlannedProcedure]


class DesignOutput(BaseModel):
    policies: list[PlannedPolicy]


class Placement(BaseModel):
    code: str
    document: str = Field(description="문서 경로. 예: p0.r1.w2")


class PlacementOutput(BaseModel):
    placements: list[Placement]


@dataclass
class RequirementBrief:
    """모델에 보여주는 요건 한 건."""

    code: str
    clause_number: str
    clause_title: str
    obligation: str
    category: str
    summary: str
    quote: str = ""
    applicability: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class PlanNode:
    """설계안의 문서 하나. path 는 설계안 안에서의 위치다(p0, p0.r1, p0.r1.w0, p0.r1.w0.t0)."""

    path: str
    doc_type: str  # POL | PRO | WI | TMP
    title: str
    purpose: str
    requirements: list[str]
    parent: str | None

    @property
    def depth(self) -> int:
        return self.path.count(".")


def _requirement_listing(requirements: list[RequirementBrief]) -> str:
    lines: list[str] = []
    clause = None
    for r in requirements:
        if r.clause_number != clause:
            clause = r.clause_number
            lines.append(f"\n## {r.clause_number} {r.clause_title}")
        evidence = f" (증적: {', '.join(r.evidence)})" if r.evidence else ""
        lines.append(f"- {r.code} [{r.obligation}/{r.category}] {r.summary}{evidence}")
    return "\n".join(lines).strip()


def flatten(structure: dict[str, Any]) -> list[PlanNode]:
    """설계안을 상위 문서가 먼저 오는 순서로 편다."""
    nodes: list[PlanNode] = []
    for pi, policy in enumerate(structure.get("policies", [])):
        p = f"p{pi}"
        nodes.append(
            PlanNode(p, "POL", policy["title"], policy["purpose"], policy["requirements"], None)
        )
        for ri, procedure in enumerate(policy.get("procedures", [])):
            r = f"{p}.r{ri}"
            nodes.append(
                PlanNode(
                    r, "PRO", procedure["title"], procedure["purpose"], procedure["requirements"], p
                )
            )
            for wi, instruction in enumerate(procedure.get("instructions", [])):
                w = f"{r}.w{wi}"
                nodes.append(
                    PlanNode(
                        w,
                        "WI",
                        instruction["title"],
                        instruction["purpose"],
                        instruction["requirements"],
                        r,
                    )
                )
                for ti, template in enumerate(instruction.get("templates", [])):
                    nodes.append(PlanNode(f"{w}.t{ti}", "TMP", template, "", [], w))
    return nodes


def normalize(structure: dict[str, Any], valid_codes: set[str]) -> tuple[dict[str, Any], list[str]]:
    """설계안을 정리한다: 없는 코드와 중복 배정을 지우고, 배정되지 않은 요건을 찾는다."""
    seen: set[str] = set()

    def clean(codes: list[str]) -> list[str]:
        kept = []
        for code in codes:
            code = code.strip()
            if code in valid_codes and code not in seen:
                seen.add(code)
                kept.append(code)
        return kept

    # 가장 구체적인 문서의 배정을 살리기 위해 아래 단계부터 정리한다.
    for policy in structure.get("policies", []):
        for procedure in policy.get("procedures", []):
            for instruction in procedure.get("instructions", []):
                instruction["requirements"] = clean(instruction.get("requirements", []))
                instruction["templates"] = [
                    t.strip() for t in instruction.get("templates", []) if t.strip()
                ][:3]
    for policy in structure.get("policies", []):
        for procedure in policy.get("procedures", []):
            procedure["requirements"] = clean(procedure.get("requirements", []))
    for policy in structure.get("policies", []):
        policy["requirements"] = clean(policy.get("requirements", []))
    return structure, sorted(valid_codes - seen)


def _apply_placements(structure: dict[str, Any], placements: list[Placement]) -> None:
    index: dict[str, dict[str, Any]] = {}
    for pi, policy in enumerate(structure["policies"]):
        index[f"p{pi}"] = policy
        for ri, procedure in enumerate(policy["procedures"]):
            index[f"p{pi}.r{ri}"] = procedure
            for wi, instruction in enumerate(procedure["instructions"]):
                index[f"p{pi}.r{ri}.w{wi}"] = instruction
    for placement in placements:
        target = index.get(placement.document.strip())
        if target is not None:
            target["requirements"].append(placement.code.strip())


@dataclass
class DesignResult:
    structure: dict[str, Any]
    uncovered: list[str]
    model: str
    input_tokens: int
    output_tokens: int


def design(requirements: list[RequirementBrief]) -> DesignResult:
    """적용요건을 문서 체계로 묶는다. 빠진 요건이 있으면 한 번 더 물어 채운다."""
    valid = {r.code for r in requirements}
    first = llm.structured(
        system=DESIGN_PROMPT,
        user=f"적용요건 {len(requirements)}건\n\n{_requirement_listing(requirements)}",
        schema=DesignOutput,
        max_tokens=48000,
    )
    structure, uncovered = normalize(first.output.model_dump(), valid)
    tokens_in, tokens_out = first.input_tokens, first.output_tokens

    if uncovered and structure["policies"]:
        documents = "\n".join(
            f"- {n.path} [{n.doc_type}] {n.title} — {n.purpose}"
            for n in flatten(structure)
            if n.doc_type != "TMP"
        )
        missing = [r for r in requirements if r.code in set(uncovered)]
        second = llm.structured(
            system=PLACEMENT_PROMPT,
            user=f"문서 목록\n{documents}\n\n배정되지 않은 요건\n{_requirement_listing(missing)}",
            schema=PlacementOutput,
        )
        _apply_placements(structure, second.output.placements)
        structure, uncovered = normalize(structure, valid)
        tokens_in += second.input_tokens
        tokens_out += second.output_tokens

    return DesignResult(structure, uncovered, first.model, tokens_in, tokens_out)


# ── 문서 작성 ────────────────────────────────────────────────────────────────

WRITE_PROMPT = """\
당신은 조직의 프로세스 문서를 쓰는 품질·프로세스 전문가입니다. 문서 하나의 정보와, 이 문서가
이행해야 하는 '적용요건'이 주어집니다. 정해진 섹션 구성에 맞춰 문서 본문을 한국어로 쓰세요.
이 문서는 사람이 검토·승인한 뒤 조직의 기준이 되고, 인증 심사에서 "이 내용은 표준의 어느
요건을 이행하는가"를 증명하는 데 쓰입니다.

작성 규칙
1. 요건을 조직이 '어떻게 이행하는지'를 씁니다. 표준 원문을 옮겨 적거나 번역해 붙이지 않습니다.
   원문과 같은 문장이 길게 이어지면 안 됩니다.
2. 주어진 요건에서 따라 나오는 내용만 씁니다. 요건에 없는 수치, 기한, 도구 이름, 부서 이름을
   지어내지 않습니다. 조직이 스스로 정해야 하는 값은 〔조직 결정: 무엇을 정해야 하는지〕 로
   표시해 둡니다. 예: 〔조직 결정: 검토 주기〕
3. 섹션마다 requirements 에 그 섹션의 내용이 근거로 삼은 요건 코드를 적습니다.
   - 주어진 요건 코드만 씁니다.
   - 이 문서에 '배정된 요건'은 모두 어느 섹션에선가 근거로 쓰여야 합니다.
   - 활동·책임·기준을 정하는 섹션은 반드시 하나 이상의 요건을 근거로 댑니다.
   - 목적이나 범위처럼 설명하는 섹션은 근거가 없으면 비워 둡니다.
4. 섹션의 key 는 주어진 것을 그대로 쓰고, 주어진 모든 섹션을 한 번씩 돌려줍니다.
   쓸 내용이 없는 선택 섹션은 body_md 를 빈 문자열로 둡니다.
5. body_md 는 Markdown 입니다. 섹션에 '형식'이 주어지면 그 표나 목록의 모양을 따릅니다.
   섹션 제목은 본문에 다시 쓰지 않습니다.
6. 역할은 조직에서 흔히 쓰는 이름으로 적되(프로세스 오너, 품질 책임자, 개발 책임자, 개발자,
   시험 담당자 등), 문서 전체에서 같은 이름을 씁니다.
7. 문서 유형에 맞게 씁니다.
   - 정책서: 원칙과 책임. 절차 수준의 단계는 쓰지 않습니다.
   - 절차서: 누가 어떤 순서로 무엇을 넘겨받고 넘겨주는지. 흐름도는 mermaid flowchart 로 그립니다.
   - 업무지침서: 실무자가 그대로 따라 할 수 있는 단계와 완료 조건.
   - 템플릿: 빈 양식입니다. 기록 항목만 두고 예시 값은 넣지 않습니다.
"""


class WrittenSection(BaseModel):
    key: str
    body_md: str
    requirements: list[str] = Field(description="이 섹션이 근거로 삼은 요건 코드")


class WrittenDocument(BaseModel):
    sections: list[WrittenSection]


@dataclass
class WriteTask:
    """문서 하나를 쓰는 데 필요한 것."""

    node: PlanNode
    section_schema: list[dict[str, Any]]
    # 이 문서에 배정된 요건(모두 근거로 쓰여야 한다)
    assigned: list[RequirementBrief]
    # 근거로 댈 수 있는 요건. 정책서는 하위 문서의 요건까지, 템플릿은 상위 지침의 요건.
    allowed: list[RequirementBrief]
    ancestors: list[str]  # 상위 문서 제목(최상위부터)
    children: list[str]  # 바로 아래 문서 제목


def _write_request(task: WriteTask, feedback: str = "") -> str:
    type_names = {"POL": "정책서", "PRO": "절차서", "WI": "업무지침서", "TMP": "템플릿"}
    parts = [
        f"문서 유형: {type_names[task.node.doc_type]}",
        f"제목: {task.node.title}",
    ]
    if task.node.purpose:
        parts.append(f"다루는 범위: {task.node.purpose}")
    if task.ancestors:
        parts.append("상위 문서: " + " > ".join(task.ancestors))
    if task.children:
        parts.append("하위 문서: " + ", ".join(task.children))

    assigned_codes = {r.code for r in task.assigned}
    parts.append("\n# 요건")
    for r in task.allowed:
        mark = "배정됨" if r.code in assigned_codes else "참고"
        scope = f" [{r.applicability}]" if r.applicability else ""
        evidence = f"\n  증적 후보: {', '.join(r.evidence)}" if r.evidence else ""
        parts.append(
            f"- {r.code} ({mark}, {r.obligation}){scope}: {r.summary}\n  원문: {r.quote}{evidence}"
        )

    parts.append("\n# 섹션 구성")
    for spec in task.section_schema:
        need = "필수" if spec.get("required") else "선택"
        line = f"- key: {spec['key']} | 제목: {spec['title']} | {need}"
        if spec.get("hint"):
            line += f" | 안내: {spec['hint']}"
        parts.append(line)
        if spec.get("template"):
            parts.append("  형식:\n" + "\n".join(f"    {t}" for t in spec["template"].splitlines()))

    if feedback:
        parts.append(
            "\n# 다시 써야 하는 이유\n"
            "앞서 쓴 본문이 다음 검사를 통과하지 못했습니다. 고쳐서 전체를 다시 쓰세요.\n"
            + feedback
        )
    return "\n".join(parts)


def check_written(task: WriteTask, written: WrittenDocument) -> list[str]:
    """근거 게이트. 통과하면 빈 목록, 아니면 사람이 읽을 수 있는 문제 목록을 돌려준다."""
    problems: list[str] = []
    by_key = {s.key: s for s in written.sections}
    schema_keys = [s["key"] for s in task.section_schema]
    allowed = {r.code for r in task.allowed}
    assigned = {r.code for r in task.assigned}

    unknown = sorted(set(by_key) - set(schema_keys))
    if unknown:
        problems.append(f"섹션 구성에 없는 key 를 썼습니다: {', '.join(unknown)}")

    cited: set[str] = set()
    for spec in task.section_schema:
        section = by_key.get(spec["key"])
        body = (section.body_md if section else "").strip()
        codes = {c.strip() for c in (section.requirements if section else [])}
        if spec.get("required") and not body:
            problems.append(f"필수 섹션 '{spec['title']}' 이(가) 비어 있습니다.")
        invalid = sorted(codes - allowed)
        if invalid:
            problems.append(
                f"'{spec['title']}' 섹션이 이 문서에 주어지지 않은 요건을 근거로 댔습니다: "
                f"{', '.join(invalid)}"
            )
        if spec.get("normative") and body and not (codes & allowed):
            problems.append(f"'{spec['title']}' 섹션에 근거 요건이 없습니다.")
        cited |= codes & allowed

    missing = sorted(assigned - cited)
    if missing:
        problems.append(f"배정된 요건 중 근거로 쓰이지 않은 것이 있습니다: {', '.join(missing)}")
    return problems


@dataclass
class WriteResult:
    sections: list[dict[str, str]]  # [{key, title, body_md}]
    citations: dict[str, list[str]]  # 섹션 key → 요건 코드
    model: str
    input_tokens: int
    output_tokens: int


class GroundingError(RuntimeError):
    """모델이 쓴 본문이 근거 게이트를 통과하지 못했다."""


def write(task: WriteTask) -> WriteResult:
    """문서 본문을 쓴다. 근거 게이트를 통과하지 못하면 한 번 다시 쓰게 하고, 그래도 안 되면 실패."""
    feedback = ""
    tokens_in = tokens_out = 0
    for _ in range(2):
        result = llm.structured(
            system=WRITE_PROMPT,
            user=_write_request(task, feedback),
            schema=WrittenDocument,
            max_tokens=32000,
        )
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        problems = check_written(task, result.output)
        if not problems:
            by_key = {s.key: s for s in result.output.sections}
            allowed = {r.code for r in task.allowed}
            sections, citations = [], {}
            for spec in task.section_schema:
                section = by_key.get(spec["key"])
                sections.append(
                    {
                        "key": spec["key"],
                        "title": spec["title"],
                        "body_md": (section.body_md if section else "").strip(),
                    }
                )
                codes = sorted(
                    {c.strip() for c in (section.requirements if section else [])} & allowed
                )
                if codes:
                    citations[spec["key"]] = codes
            return WriteResult(sections, citations, result.model, tokens_in, tokens_out)
        feedback = "\n".join(f"- {p}" for p in problems)
    raise GroundingError("근거 검사를 통과하지 못했습니다: " + feedback.replace("\n", " "))
