"""적용요건 승인 → 문서 구조 설계 → 문서 생성.

모델 호출은 가짜로 바꾼다. 확인하는 것은 그 사이의 규칙이다: 승인 전에는 설계할 수 없고,
모든 적용요건이 문서에 배정돼야 하며, 근거가 맞지 않는 본문은 저장되지 않는다.
"""

import io
import re
import zipfile

import pytest

from app import llm, worker
from app.pipelines import planning
from app.pipelines.planning import (
    DesignOutput,
    ExtendOutput,
    PlacementOutput,
    RequirementBrief,
    WriteTask,
    WrittenDocument,
)
from tests.conftest import add_member, new_system, new_tenant
from tests.test_sources import ANSWERS, _fake_llm, _upload, fake_pdf  # noqa: F401

# 확정되는 요건(지어낸 한 건은 제외된다). 설계안에서는 원문 약칭을 붙여 부른다.
CODES = ["IEC99999 2.1.1-01", "IEC99999 2.1.2-01", "IEC99999 2.2-01"]
OTHER = ["IEC88888 2.1.1-01", "IEC88888 2.1.2-01", "IEC88888 2.2-01"]


def _structure(instruction_codes=tuple(CODES[:2]), procedure_codes=tuple(CODES[2:]), note=""):
    return {
        "policies": [
            {
                "title": "개발 정책",
                "purpose": "개발 원칙",
                "requirements": [],
                "procedures": [
                    {
                        "title": "개발 계획 절차",
                        "purpose": "계획 수립 흐름",
                        "requirements": list(procedure_codes),
                        "integration_note": "",
                        "instructions": [
                            {
                                "title": "개발 계획 수립 지침",
                                "purpose": "계획서 작성 방법",
                                "requirements": list(instruction_codes),
                                "integration_note": note,
                                "templates": ["개발 계획서"],
                            }
                        ],
                    }
                ],
            }
        ]
    }


# ── 설계안 정리와 근거 게이트(순수 함수) ─────────────────────────────────────


def test_normalize_drops_unknown_and_duplicate_codes_and_reports_uncovered():
    structure = _structure(
        # 약칭과 번호 사이의 공백을 다르게 적어도 같은 코드로 본다.
        instruction_codes=("IEC99999  2.1.1-01", "IEC99999 9.9-99"),
        procedure_codes=(CODES[0],),
    )
    cleaned, uncovered = planning.normalize(structure, set(CODES))
    procedure = cleaned["policies"][0]["procedures"][0]
    # 없는 코드는 지워지고, 중복 배정은 더 구체적인 문서(지침) 쪽만 남는다.
    assert procedure["instructions"][0]["requirements"] == [CODES[0]]
    assert procedure["requirements"] == []
    assert uncovered == CODES[1:]


def test_codes_are_grouped_by_standard():
    assert planning.by_standard([CODES[0], OTHER[0], CODES[2]]) == {
        "IEC99999": ["2.1.1-01", "2.2-01"],
        "IEC88888": ["2.1.1-01"],
    }


def test_flatten_orders_parents_first():
    nodes = planning.flatten(_structure())
    assert [(n.path, n.doc_type, n.parent) for n in nodes] == [
        ("p0", "POL", None),
        ("p0.r0", "PRO", "p0"),
        ("p0.r0.w0", "WI", "p0.r0"),
        ("p0.r0.w0.t0", "TMP", "p0.r0.w0"),
    ]


def _brief(code):
    return RequirementBrief(code, "2.1", "Planning", "shall", "documentation", "요약", "quote")


def _write_task():
    node = planning.flatten(_structure())[2]
    schema = [
        {"key": "purpose", "title": "업무 목적", "required": True},
        {"key": "steps", "title": "수행 단계", "required": True, "normative": True},
        {"key": "note", "title": "비고", "required": False},
    ]
    assigned = [_brief(CODES[0]), _brief(CODES[1])]
    return WriteTask(node, schema, assigned, assigned, ["개발 정책", "개발 계획 절차"], [])


def _written(steps_codes, purpose="목적", steps="1. 계획을 세운다."):
    return WrittenDocument.model_validate(
        {
            "sections": [
                {"key": "purpose", "body_md": purpose, "requirements": []},
                {"key": "steps", "body_md": steps, "requirements": steps_codes},
                {"key": "note", "body_md": "", "requirements": []},
            ]
        }
    )


def test_grounding_gate():
    task = _write_task()
    assert planning.check_written(task, _written(CODES[:2])) == []

    # 배정된 요건을 근거로 쓰지 않았다.
    problems = planning.check_written(task, _written(CODES[:1]))
    assert any("2.1.2-01" in p for p in problems)
    # 이 문서에 주어지지 않은 요건을 근거로 댔다. 번호가 같아도 다른 표준의 요건이면 안 된다.
    problems = planning.check_written(task, _written([*CODES[:2], OTHER[0]]))
    assert any("주어지지 않은 요건" in p for p in problems)
    # 활동을 정하는 섹션에 근거가 없다.
    assert any("근거 요건이 없습니다" in p for p in planning.check_written(task, _written([])))
    # 필수 섹션이 비었다.
    problems = planning.check_written(task, _written(CODES[:2], purpose=" "))
    assert any("비어 있습니다" in p for p in problems)


def test_write_retries_once_with_feedback_then_fails(monkeypatch):
    calls = []

    def structured(*, system, user, schema, **_):
        calls.append(user)
        return llm.LLMResult(_written(CODES[:1]), "fake-model", 10, 10)

    monkeypatch.setattr(llm, "structured", structured)
    with pytest.raises(planning.GroundingError, match="2.1.2-01"):
        planning.write(_write_task())
    assert len(calls) == 2 and "다시 써야 하는 이유" in calls[1]


# ── API 흐름 ─────────────────────────────────────────────────────────────────


def _confirmed_source(consultant, tenant, monkeypatch, data=b"%PDF-1.7 fake", code="iec99999"):
    source_id = _upload(consultant, tenant, data, code).json()["id"]
    base = f"/api/t/{tenant}/sources/{source_id}"
    _fake_llm(monkeypatch, ANSWERS)
    consultant.post(f"{base}/mine")
    worker.process_next_run()
    invented = next(
        r for r in consultant.get(f"{base}/requirements").json() if not r["quote_verified"]
    )
    consultant.patch(f"/api/t/{tenant}/requirements/{invented['id']}", json={"status": "rejected"})
    assert consultant.post(f"{base}/confirm").status_code == 200
    return source_id


def _fake_generation(monkeypatch, structure, bad_titles=(), extension=None, prompts=None):
    """설계에는 structure 를, 문서 작성에는 근거 게이트를 통과하는 본문을 돌려준다.

    bad_titles 의 문서는 근거 없는 본문을 돌려준다(게이트에서 걸려야 한다).
    """

    def structured(*, system, user, schema, **_):
        if prompts is not None:
            prompts.append(user)
        if schema is ExtendOutput:
            return llm.LLMResult(ExtendOutput.model_validate(extension), "fake-model", 80, 40)
        if schema is DesignOutput:
            return llm.LLMResult(DesignOutput.model_validate(structure), "fake-model", 100, 100)
        if schema is PlacementOutput:
            return llm.LLMResult(PlacementOutput(placements=[]), "fake-model", 10, 10)
        title = next(line[4:] for line in user.splitlines() if line.startswith("제목: "))
        listed = re.findall(r"^- (.+?) [(](배정됨|참고)", user, re.MULTILINE)
        codes = [code for code, mark in listed if mark == "배정됨"] or [c for c, _ in listed]
        keys = [
            line.split(" | ")[0][7:] for line in user.splitlines() if line.startswith("- key: ")
        ]
        cite = [] if title in bad_titles else codes
        sections = [{"key": key, "body_md": f"{title} 본문", "requirements": cite} for key in keys]
        return llm.LLMResult(
            WrittenDocument.model_validate({"sections": sections}), "fake-model", 50, 50
        )

    monkeypatch.setattr(llm, "structured", structured)


def _approved_basis(consultant, tenant, monkeypatch):
    source_id = _confirmed_source(consultant, tenant, monkeypatch)
    new_system(consultant, tenant)
    system = f"/api/t/{tenant}/systems/ims"
    assert consultant.post(f"{system}/basis", json={"source_id": source_id}).status_code == 201
    assert consultant.post(f"{system}/basis/{source_id}/approve").status_code == 200
    return source_id, system


def test_basis_must_be_confirmed_reviewed_and_approved(consultant, fake_pdf, monkeypatch):  # noqa: F811
    tenant = new_tenant(consultant)
    new_system(consultant, tenant)
    system = f"/api/t/{tenant}/systems/ims"

    # 요건을 확정하지 않은 원문은 근거가 될 수 없다.
    draft_source = _upload(consultant, tenant, b"%PDF-1.7 another").json()["id"]
    response = consultant.post(f"{system}/basis", json={"source_id": draft_source})
    assert response.json()["detail"]["code"] == "source_not_confirmed"
    consultant.delete(f"/api/t/{tenant}/sources/{draft_source}")

    source_id = _confirmed_source(consultant, tenant, monkeypatch)
    assert [s["id"] for s in consultant.get(f"{system}/basis").json()["available"]] == [source_id]
    basis = consultant.post(f"{system}/basis", json={"source_id": source_id}).json()
    assert basis["items"][0]["total"] == 3 and basis["available"] == []
    assert set(basis["items"][0]["actions"]) == {"review", "detach", "approve"}

    # 승인 전에는 문서 구조를 설계할 수 없다.
    start = {"source_ids": [source_id], "scope_code": "QMS"}
    assert (
        consultant.post(f"{system}/plans", json=start).json()["detail"]["code"]
        == "basis_not_approved"
    )

    # 적용하지 않는 요건은 사유가 있어야 제외할 수 있다.
    requirements = consultant.get(f"{system}/basis/{source_id}/requirements").json()
    target = f"{system}/basis/{source_id}/requirements/{requirements[2]['id']}"
    assert (
        consultant.put(target, json={"excluded": True}).json()["detail"]["code"]
        == "reason_required"
    )
    assert (
        consultant.put(target, json={"excluded": True, "reason": "검증은 외부 위탁"}).status_code
        == 204
    )
    listed = consultant.get(f"{system}/basis/{source_id}/requirements").json()
    assert [(r["code"], r["excluded"]) for r in listed] == [
        ("2.1.1-01", False),
        ("2.1.2-01", False),
        ("2.2-01", True),
    ]

    approved = consultant.post(f"{system}/basis/{source_id}/approve").json()["items"][0]
    assert approved["excluded"] == 1 and approved["approved_by"]["name"] == "컨설턴트"
    # 아직 문서가 없으니 적용요건은 모두 미이행이고, 제외한 요건은 사유와 함께 따로 센다.
    coverage = consultant.get(f"{system}/coverage").json()["sources"][0]
    assert (coverage["total"], coverage["excluded"], coverage["gaps"]) == (3, 1, 2)
    assert [(r["code"], r["status"], r["reason"]) for r in coverage["requirements"]] == [
        ("2.1.1-01", "gap", ""),
        ("2.1.2-01", "gap", ""),
        ("2.2-01", "excluded", "검증은 외부 위탁"),
    ]
    assert coverage["chapters"] == [{"key": "2", "title": "Requirements"}]
    assert set(approved["actions"]) == {"reopen", "design"}
    # 승인한 뒤에는 적용요건을 바꿀 수 없다. 바꾸려면 승인을 취소한다.
    assert (
        consultant.put(target, json={"excluded": False}).json()["detail"]["code"]
        == "basis_approved"
    )
    assert consultant.post(f"{system}/basis/{source_id}/reopen").status_code == 200
    assert consultant.put(target, json={"excluded": False}).status_code == 204


def test_design_then_write_documents_with_citations(consultant, fake_pdf, monkeypatch):  # noqa: F811
    tenant = new_tenant(consultant)
    source_id, system = _approved_basis(consultant, tenant, monkeypatch)
    _fake_generation(monkeypatch, _structure())

    plan = consultant.post(
        f"{system}/plans", json={"source_ids": [source_id], "scope_code": "QMS"}
    ).json()
    assert plan["status"] == "designing" and plan["actions"] == []
    worker.process_next_run()

    plan = consultant.get(f"{system}/plans").json()[0]
    assert (
        plan["status"] == "proposed" and plan["uncovered"] == [] and plan["applicable_count"] == 3
    )
    assert [(n["doc_type"], n["title"], n["status"]) for n in plan["nodes"]] == [
        ("POL", "개발 정책", "pending"),
        ("PRO", "개발 계획 절차", "pending"),
        ("WI", "개발 계획 수립 지침", "pending"),
        ("TMP", "개발 계획서", "pending"),
    ]
    assert plan["actions"] == ["write", "edit", "discard"]
    # 설계안이 있는 동안에는 적용요건 승인을 취소할 수 없다.
    response = consultant.post(f"{system}/basis/{source_id}/reopen")
    assert response.json()["detail"]["code"] == "plan_exists"

    writing = consultant.post(f"{system}/plans/{plan['id']}/write", json={}).json()
    assert writing["status"] == "writing" and writing["actions"] == []
    worker.process_next_run()

    done = consultant.get(f"{system}/plans").json()[0]
    assert done["status"] == "done" and done["actions"] == []
    assert done["run"]["progress"]["done"] == 4 and done["run"]["progress"]["failed"] == 0
    assert all(n["status"] == "done" and n["document_id"] for n in done["nodes"])

    # 문서는 계층과 번호를 갖춘 초안으로 만들어지고, 모델이 썼다는 표시가 남는다.
    documents = consultant.get(f"{system}/documents").json()
    assert [(d["code"], d["open_status"]) for d in documents] == [
        ("POL-QMS-01", "draft"),
        ("PRO-QMS-01-01", "draft"),
        ("TMP-QMS-01-01-01-01", "draft"),
        ("WI-QMS-01-01-01", "draft"),
    ]
    wi = next(n for n in done["nodes"] if n["doc_type"] == "WI")
    detail = consultant.get(f"/api/t/{tenant}/documents/{wi['document_id']}").json()
    revision = detail["open"]
    assert revision["generated_by"] == "fake-model"
    assert revision["sections"][0]["body_md"] == "개발 계획 수립 지침 본문"
    assert revision["change_summary"] == "IEC99999 적용요건에서 생성"
    wi_plan = next(n for n in done["nodes"] if n["doc_type"] == "WI")
    assert wi_plan["requirements"] == CODES[:2]
    assert wi_plan["by_standard"] == {"IEC99999": ["2.1.1-01", "2.1.2-01"]}

    # 섹션별 근거 요건을 원문 인용과 함께 조회할 수 있다.
    links = consultant.get(f"/api/t/{tenant}/revisions/{revision['id']}/requirements").json()
    steps = [link for link in links if link["section_key"] == "steps"]
    assert [link["requirement"]["code"] for link in steps] == ["2.1.1-01", "2.1.2-01"]
    assert steps[0]["requirement"]["quote_verified"] and steps[0]["source"]["code"] == "IEC99999"

    # 커버리지: 초안만 있는 동안은 '초안', 승인된 문서가 인용하면 '이행'이 된다.
    coverage = consultant.get(f"{system}/coverage").json()["sources"][0]
    assert (coverage["covered"], coverage["drafted"], coverage["gaps"]) == (0, 3, 0)
    cited = {r["code"]: {d["code"]: d for d in r["documents"]} for r in coverage["requirements"]}
    # 지침에 배정된 요건은 지침과, 그 요건을 근거로 댄 정책·템플릿에서 이행된다.
    assert set(cited["2.1.1-01"]) == {"POL-QMS-01", "WI-QMS-01-01-01", "TMP-QMS-01-01-01-01"}
    assert set(cited["2.2-01"]) == {"POL-QMS-01", "PRO-QMS-01-01"}
    assert cited["2.1.1-01"]["WI-QMS-01-01-01"]["state"] == "draft"
    assert "수행 단계" in cited["2.1.1-01"]["WI-QMS-01-01-01"]["sections"]

    reviewer = add_member(consultant, tenant, "품질 책임자", ["qmr"])
    pol = next(n for n in done["nodes"] if n["doc_type"] == "POL")
    pol_revision = consultant.get(f"/api/t/{tenant}/documents/{pol['document_id']}").json()["open"]
    assert (
        consultant.post(f"/api/t/{tenant}/revisions/{pol_revision['id']}/submit").status_code == 200
    )
    approve = f"/api/t/{tenant}/revisions/{pol_revision['id']}/approve"
    assert reviewer.post(approve, json={}).status_code == 200
    coverage = reviewer.get(f"{system}/coverage").json()["sources"][0]
    # 정책이 세 요건을 모두 인용하므로 모두 '이행'이 된다. 문서별 상태는 따로 보인다.
    assert (coverage["covered"], coverage["drafted"], coverage["gaps"]) == (3, 0, 0)
    states = {d["code"]: d["state"] for d in coverage["requirements"][0]["documents"]}
    assert states == {
        "POL-QMS-01": "approved",
        "WI-QMS-01-01-01": "draft",
        "TMP-QMS-01-01-01-01": "draft",
    }

    # 심사: 양식으로 발행한 기록이 그 양식과 그 지침이 이행하는 요건의 증적으로 이어진다.
    tmp = next(n for n in done["nodes"] if n["doc_type"] == "TMP")
    tmp_revision = consultant.get(f"/api/t/{tenant}/documents/{tmp['document_id']}").json()["open"]
    table = "| 항목 | 내용 |\n|---|---|\n| 작성자 |  |\n| 내용 |  |"
    sections = [
        {**s, "body_md": table if s["key"] == "fields" else s["body_md"]}
        for s in tmp_revision["sections"]
    ]
    consultant.patch(f"/api/t/{tenant}/revisions/{tmp_revision['id']}", json={"sections": sections})
    upload = consultant.post(
        f"{system}/artifacts", files={"file": ("plan.txt", "개발 계획서\n작성: 김개발".encode())}
    ).json()
    artifact = consultant.put(
        f"/api/t/{tenant}/artifacts/{upload['id']}/template",
        json={"document_id": tmp["document_id"]},
    ).json()
    record_path = f"/api/t/{tenant}/records/{artifact['record']['id']}"
    consultant.patch(
        record_path,
        json={"performed_on": "2024-03-05", "fields": [{"name": "작성자", "value": "김개발"}]},
    )
    assert consultant.post(f"{record_path}/publish").status_code == 200

    coverage = consultant.get(f"{system}/coverage").json()["sources"][0]
    evidence = {r["code"]: [x["code"] for x in r["records"]] for r in coverage["requirements"]}
    # 지침(WI)이 이행하는 요건은 그 아래 양식의 기록으로 증적이 생긴다. 절차 요건에는 없다.
    assert evidence == {
        "2.1.1-01": ["REC-QMS-01-01-01-01-001"],
        "2.1.2-01": ["REC-QMS-01-01-01-01-001"],
        "2.2-01": [],
    }
    assert coverage["evidenced"] == 2
    # 기간 밖의 기록은 세지 않는다.
    later = consultant.get(f"{system}/coverage?date_from=2024-04-01").json()
    assert later["date_from"] == "2024-04-01" and later["sources"][0]["evidenced"] == 0

    pack = consultant.get(f"{system}/audit-pack.xlsx?date_to=2024-12-31")
    assert pack.status_code == 200
    assert pack.headers["content-type"].startswith("application/vnd.openxmlformats")
    with zipfile.ZipFile(io.BytesIO(pack.content)) as book:
        assert "xl/worksheets/sheet2.xml" in book.namelist()
        sheet = book.read("xl/worksheets/sheet2.xml").decode()
        assert "REC-QMS-01-01-01-01-001" in sheet and "WI-QMS-01-01-01" in sheet
        assert "IEC99999" in book.read("xl/workbook.xml").decode()

    # 하위 체계는 근거와 문서를 물려받는다. 문서를 제외하면 그 문서는 이행 문서에서 빠진다.
    baseline_id = consultant.get(system).json()["id"]
    new_system(consultant, tenant, slug="dev", parent_id=baseline_id)
    child = f"/api/t/{tenant}/systems/dev"
    inherited = consultant.get(f"{child}/coverage").json()["sources"][0]
    assert inherited["source"]["code"] == "IEC99999"
    assert (inherited["covered"], inherited["drafted"], inherited["gaps"]) == (3, 0, 0)
    exclusion = f"{child}/tailoring/{wi['document_id']}/exclusion"
    assert consultant.put(exclusion, json={"reason": "개발은 외주로 한다"}).status_code == 204
    tailored = consultant.get(f"{child}/coverage").json()["sources"][0]
    # 지침과 그 아래 양식이 빠져, 그 요건은 정책에서만 이행된다.
    assert [d["code"] for d in tailored["requirements"][0]["documents"]] == ["POL-QMS-01"]

    # 문서 생성을 시작한 설계안은 고칠 수 없다.
    late = consultant.put(f"{system}/plans/{plan['id']}", json=_structure())
    assert late.status_code == 409 and late.json()["detail"]["code"] == "invalid_status"

    # 같은 원문으로 다시 생성할 수 없다(문서가 중복된다).
    again = consultant.post(
        f"{system}/plans", json={"source_ids": [source_id], "scope_code": "QMS"}
    )
    assert again.json()["detail"]["code"] == "plan_exists"


def test_several_standards_are_integrated_into_one_system(consultant, fake_pdf, monkeypatch):  # noqa: F811
    tenant = new_tenant(consultant)
    # 두 표준의 조항 번호가 같다(둘 다 2.1.1-01 …). 약칭으로 구분돼야 한다.
    first = _confirmed_source(consultant, tenant, monkeypatch)
    second = _confirmed_source(consultant, tenant, monkeypatch, b"%PDF-1.7 second", "iec88888")
    same_code = _confirmed_source(consultant, tenant, monkeypatch, b"%PDF-1.7 third", "iec99999")
    new_system(consultant, tenant)
    system = f"/api/t/{tenant}/systems/ims"
    for source_id in (first, second, same_code):
        assert consultant.post(f"{system}/basis", json={"source_id": source_id}).status_code == 201
        assert consultant.post(f"{system}/basis/{source_id}/approve").status_code == 200

    # 약칭이 같은 원문은 함께 설계할 수 없다(요건을 구분할 수 없다).
    clash = consultant.post(
        f"{system}/plans", json={"source_ids": [first, same_code], "scope_code": "QMS"}
    )
    assert clash.json()["detail"]["code"] == "duplicate_source_code"

    note = "두 표준 모두 개발 계획을 요구하고, IEC88888 은 보안 활동을 계획에 더 넣게 한다."
    _fake_generation(
        monkeypatch,
        _structure(
            instruction_codes=(*CODES[:2], *OTHER[:2]),
            procedure_codes=(CODES[2], OTHER[2]),
            note=note,
        ),
    )
    start = {"source_ids": [first, second], "scope_code": "QMS"}
    plan = consultant.post(f"{system}/plans", json=start).json()
    assert [s["code"] for s in plan["sources"]] == ["IEC99999", "IEC88888"]
    worker.process_next_run()

    plan = consultant.get(f"{system}/plans").json()[0]
    assert plan["status"] == "proposed" and plan["uncovered"] == []
    assert plan["applicable_count"] == 6
    assert plan["applicable_by_standard"] == {"IEC99999": 3, "IEC88888": 3}
    # 지침 하나가 두 표준의 겹치는 요건을 함께 이행한다.
    wi = next(n for n in plan["nodes"] if n["doc_type"] == "WI")
    assert wi["by_standard"] == {
        "IEC99999": ["2.1.1-01", "2.1.2-01"],
        "IEC88888": ["2.1.1-01", "2.1.2-01"],
    }
    assert wi["integration_note"] == note
    assert "여러 표준의 요건을 함께 이행하는 문서 2건" in plan["run"]["events"]

    # 설계안에 든 원문은 둘 다 묶인다: 승인을 취소할 수도, 다른 설계안에 쓸 수도 없다.
    items = {i["source"]["id"]: i for i in consultant.get(f"{system}/basis").json()["items"]}
    assert items[first]["actions"] == [] and items[second]["actions"] == []
    assert "design" in items[same_code]["actions"]
    again = consultant.post(f"{system}/plans", json={"source_ids": [second], "scope_code": "QMS"})
    assert again.json()["detail"]["code"] == "plan_exists"

    consultant.post(f"{system}/plans/{plan['id']}/write", json={})
    worker.process_next_run()
    done = consultant.get(f"{system}/plans").json()[0]
    assert done["status"] == "done"

    # 문서의 한 섹션이 두 표준의 요건을 각각의 원문과 함께 근거로 댄다.
    wi = next(n for n in done["nodes"] if n["doc_type"] == "WI")
    revision = consultant.get(f"/api/t/{tenant}/documents/{wi['document_id']}").json()["open"]
    assert revision["change_summary"] == "IEC99999, IEC88888 적용요건에서 생성"
    links = consultant.get(f"/api/t/{tenant}/revisions/{revision['id']}/requirements").json()
    cited = {
        (link["source"]["code"], link["requirement"]["code"])
        for link in links
        if link["section_key"] == "steps"
    }
    assert cited == {
        ("IEC99999", "2.1.1-01"),
        ("IEC99999", "2.1.2-01"),
        ("IEC88888", "2.1.1-01"),
        ("IEC88888", "2.1.2-01"),
    }


def test_a_new_standard_is_added_to_existing_documents(consultant, fake_pdf, monkeypatch):  # noqa: F811
    tenant = new_tenant(consultant)
    first, system = _approved_basis(consultant, tenant, monkeypatch)
    _fake_generation(monkeypatch, _structure())
    plan_id = consultant.post(
        f"{system}/plans", json={"source_ids": [first], "scope_code": "QMS"}
    ).json()["id"]
    worker.process_next_run()
    consultant.post(f"{system}/plans/{plan_id}/write", json={})
    worker.process_next_run()
    documents = {d["code"]: d for d in consultant.get(f"{system}/documents").json()}
    wi_id = documents["WI-QMS-01-01-01"]["id"]
    # 지침은 승인해 둔다(승인판이 있는 문서는 새 개정판으로 고친다). 정책·절차는 초안 그대로.
    reviewer = add_member(consultant, tenant, "품질 책임자", ["qmr"])
    for code in ("POL-QMS-01", "PRO-QMS-01-01", "WI-QMS-01-01-01"):
        revision = documents[code]["open_revision_id"]
        consultant.post(f"/api/t/{tenant}/revisions/{revision}/submit")
        assert (
            reviewer.post(f"/api/t/{tenant}/revisions/{revision}/approve", json={}).status_code
            == 200
        )

    # 새 표준을 근거로 더한다. 기존 문서가 있는 체계에서는 새로 설계하지 않고 기존 문서에 반영한다.
    second = _confirmed_source(consultant, tenant, monkeypatch, b"%PDF-1.7 second", "iec88888")
    consultant.post(f"{system}/basis", json={"source_id": second})
    consultant.post(f"{system}/basis/{second}/approve")
    extension = {
        "updates": [
            {
                "document": "d2",
                "requirements": OTHER[:2],
                "integration_note": "d1 의 흐름에 보안 활동을 더한다",
            },
            {"document": "d9", "requirements": [], "integration_note": ""},  # 없는 문서는 버린다
        ],
        "additions": [
            {
                "doc_type": "WI",
                "parent": "d1",
                "title": "보안 검증 지침",
                "purpose": "보안 검증 방법",
                "requirements": [OTHER[2]],
                "integration_note": "",
                "templates": ["보안 검증 기록"],
            },
            # 정책 아래에 지침을 붙일 수는 없다(버린다).
            {
                "doc_type": "WI",
                "parent": "d0",
                "title": "잘못된 지침",
                "purpose": "",
                "requirements": [],
                "integration_note": "",
                "templates": [],
            },
        ],
    }
    prompts: list[str] = []
    _fake_generation(monkeypatch, _structure(), extension=extension, prompts=prompts)
    start = {"source_ids": [second], "mode": "extend"}
    plan = consultant.post(f"{system}/plans", json=start).json()
    assert plan["mode"] == "extend" and plan["scope_code"] == ""
    worker.process_next_run()
    # 모델에는 기존 문서를 키로 보여주고, 각 문서가 이미 무엇을 다루는지 함께 준다.
    assert "d2 [WI] WI-QMS-01-01-01 개발 계획 수립 지침 — 다루는 요건: 요약" in prompts[0]

    plan = next(p for p in consultant.get(f"{system}/plans").json() if p["id"] == plan["id"])
    assert plan["status"] == "proposed" and plan["uncovered"] == []
    assert plan["actions"] == ["write", "discard"]  # 기존 문서 반영안은 아직 직접 고칠 수 없다
    assert [
        (n["path"], n["doc_type"], n["title"], (n["target"] or n["anchor"] or {}).get("code"))
        for n in plan["nodes"]
    ] == [
        ("u0", "WI", "개발 계획 수립 지침", "WI-QMS-01-01-01"),
        ("a0", "WI", "보안 검증 지침", "PRO-QMS-01-01"),
        ("a0.t0", "TMP", "보안 검증 기록", None),
    ]

    # 모델이 문서를 키로 가리키면 사람이 읽을 수 있게 제목으로 바꾼다.
    assert plan["nodes"][0]["integration_note"] == "‘개발 계획 절차’ 의 흐름에 보안 활동을 더한다"

    consultant.post(f"{system}/plans/{plan['id']}/write", json={})
    worker.process_next_run()
    plan = next(p for p in consultant.get(f"{system}/plans").json() if p["id"] == plan["id"])
    assert plan["status"] == "done", plan["nodes"]
    # 개정 지시에는 지금 본문과, 새로 반영할 요건이 들어 있다.
    revise = next(p for p in prompts if "# 개정 지시" in p)
    assert "IEC88888 2.1.1-01, IEC88888 2.1.2-01" in revise and "# 지금 본문" in revise

    # 승인판이 있던 지침은 새 개정판(주요 개정)으로 고쳐지고, 옛 근거와 새 근거를 함께 댄다.
    detail = consultant.get(f"/api/t/{tenant}/documents/{wi_id}").json()
    assert detail["approved"]["version"] == "1.0" and detail["open"]["version"] == "2.0"
    assert detail["open"]["change_summary"] == "IEC88888 적용요건 반영"
    links = consultant.get(f"/api/t/{tenant}/revisions/{detail['open']['id']}/requirements").json()
    cited = {(x["source"]["code"], x["requirement"]["code"]) for x in links}
    assert cited == {
        ("IEC99999", "2.1.1-01"),
        ("IEC99999", "2.1.2-01"),
        ("IEC88888", "2.1.1-01"),
        ("IEC88888", "2.1.2-01"),
    }
    # 새 지침은 기존 절차 아래에 같은 번호 체계로 생긴다.
    codes = [d["code"] for d in consultant.get(f"{system}/documents").json()]
    assert "WI-QMS-01-01-02" in codes and "TMP-QMS-01-01-02-01" in codes
    coverage = consultant.get(f"{system}/coverage").json()["sources"]
    new_standard = next(s for s in coverage if s["source"]["code"] == "IEC88888")
    assert new_standard["gaps"] == 0 and new_standard["drafted"] == 3

    # 기존 문서가 없는 체계에서는 반영할 수 없다.
    new_system(consultant, tenant, slug="empty")
    empty = f"/api/t/{tenant}/systems/empty"
    consultant.post(f"{empty}/basis", json={"source_id": second})
    consultant.post(f"{empty}/basis/{second}/approve")
    refused = consultant.post(f"{empty}/plans", json=start)
    assert refused.json()["detail"]["code"] == "no_documents"


def test_examples_are_written_for_each_form(consultant, fake_pdf, monkeypatch):  # noqa: F811
    from app.pipelines.examples import ExampleOutput

    tenant = new_tenant(consultant)
    source_id, system = _approved_basis(consultant, tenant, monkeypatch)
    _fake_generation(monkeypatch, _structure())
    plan_id = consultant.post(
        f"{system}/plans", json={"source_ids": [source_id], "scope_code": "QMS"}
    ).json()["id"]
    worker.process_next_run()
    consultant.post(f"{system}/plans/{plan_id}/write", json={})
    worker.process_next_run()
    documents = {d["code"]: d for d in consultant.get(f"{system}/documents").json()}
    form = documents["TMP-QMS-01-01-01-01"]
    revision = consultant.get(f"/api/t/{tenant}/revisions/{form['open_revision_id']}").json()
    table = "| 항목 | 내용 |\n|---|---|\n| 작성자 |  |\n| 승인 |  |"
    sections = [
        {**s, "body_md": table if s["key"] == "fields" else s["body_md"]}
        for s in revision["sections"]
    ]
    consultant.patch(f"/api/t/{tenant}/revisions/{revision['id']}", json={"sections": sections})

    state = consultant.get(f"{system}/examples").json()
    assert [m["code"] for m in state["missing"]] == ["TMP-QMS-01-01-01-01"] and state["run"] is None
    viewer = add_member(consultant, tenant, "구성원", [])
    assert viewer.post(f"{system}/examples").status_code == 403

    prompts: list[str] = []
    SAMPLE = "| 항목 | 예시값 | 작성 요령 |\n|---|---|---|\n| 작성자 | 개발자 A | 이름 |"

    def structured(*, system, user, schema, **_):
        prompts.append(user)
        assert schema is ExampleOutput
        return llm.LLMResult(
            ExampleOutput.model_validate(
                {
                    "sections": [
                        {"key": "sample", "body_md": SAMPLE},
                        {"key": "cautions", "body_md": "- 날짜를 확인한다"},
                        {"key": "bad_examples", "body_md": "- **잘못된 예**: 빈칸"},
                    ]
                }
            ),
            "fake-model",
            30,
            20,
        )

    monkeypatch.setattr(llm, "structured", structured)
    assert consultant.post(f"{system}/examples").json()["run"]["status"] == "queued"
    assert consultant.post(f"{system}/examples").json()["detail"]["code"] == "run_in_progress"
    worker.process_next_run()

    # 양식 항목, 지침 본문, 지침이 이행하는 요건이 함께 주어진다.
    assert "- 작성자\n- 승인" in prompts[0] and "IEC99999 2.1.1-01" in prompts[0]
    state = consultant.get(f"{system}/examples").json()
    assert state["missing"] == [] and state["run"]["progress"]["done"] == 1
    documents = {d["code"]: d for d in consultant.get(f"{system}/documents").json()}
    example = documents["EX-QMS-01-01-01-01"]
    assert example["title"] == "개발 계획서 작성예시" and example["parent_id"] == form["parent_id"]
    detail = consultant.get(f"/api/t/{tenant}/documents/{example['id']}").json()
    assert detail["open"]["generated_by"] == "fake-model"
    assert detail["open"]["sections"][0]["body_md"].startswith("| 항목 | 예시값")
    # 예시와 양식은 서로를 가리킨다.
    assert detail["example_of"]["code"] == "TMP-QMS-01-01-01-01"
    form_detail = consultant.get(f"/api/t/{tenant}/documents/{form['id']}").json()
    assert form_detail["example"]["code"] == "EX-QMS-01-01-01-01"
    # 작성예시는 기록 양식으로 고를 수 없다.
    templates = consultant.get(f"{system}/record-templates").json()
    assert [t["document"]["code"] for t in templates] == ["TMP-QMS-01-01-01-01"]
    again = consultant.post(f"{system}/examples")
    assert again.json()["detail"]["code"] == "nothing_to_write"


def test_ungrounded_documents_are_not_saved_and_can_be_retried(consultant, fake_pdf, monkeypatch):  # noqa: F811
    tenant = new_tenant(consultant)
    source_id, system = _approved_basis(consultant, tenant, monkeypatch)

    # 절차서 본문이 근거를 대지 않는다 → 저장되지 않고, 그 아래 문서는 건너뛴다.
    _fake_generation(monkeypatch, _structure(), bad_titles={"개발 계획 절차"})
    plan_id = consultant.post(
        f"{system}/plans", json={"source_ids": [source_id], "scope_code": "QMS"}
    ).json()["id"]
    worker.process_next_run()
    consultant.post(f"{system}/plans/{plan_id}/write", json={})
    worker.process_next_run()

    partial = consultant.get(f"{system}/plans").json()[0]
    assert partial["status"] == "partial"
    statuses = {n["title"]: (n["status"], n["error"]) for n in partial["nodes"]}
    assert statuses["개발 정책"][0] == "done"
    assert (
        statuses["개발 계획 절차"][0] == "failed" and "근거 검사" in statuses["개발 계획 절차"][1]
    )
    assert "건너뛰었습니다" in statuses["개발 계획 수립 지침"][1]
    assert [d["code"] for d in consultant.get(f"{system}/documents").json()] == ["POL-QMS-01"]
    # 문서를 하나라도 만든 설계안은 버릴 수 없고, 남은 문서만 다시 생성할 수 있다.
    assert partial["actions"] == ["write"]
    assert consultant.delete(f"{system}/plans/{plan_id}").status_code == 409

    _fake_generation(monkeypatch, _structure())
    consultant.post(f"{system}/plans/{plan_id}/write", json={})
    worker.process_next_run()
    done = consultant.get(f"{system}/plans").json()[0]
    assert done["status"] == "done" and done["run"]["progress"]["total"] == 3
    assert len(consultant.get(f"{system}/documents").json()) == 4


def test_uncovered_requirements_block_writing(consultant, fake_pdf, monkeypatch):  # noqa: F811
    tenant = new_tenant(consultant)
    source_id, system = _approved_basis(consultant, tenant, monkeypatch)
    _fake_generation(monkeypatch, _structure(procedure_codes=()))  # 2.2-01 이 빠진 설계

    plan_id = consultant.post(
        f"{system}/plans", json={"source_ids": [source_id], "scope_code": "QMS"}
    ).json()["id"]
    worker.process_next_run()
    plan = consultant.get(f"{system}/plans").json()[0]
    assert plan["uncovered"] == [CODES[2]] and plan["actions"] == ["edit", "discard"]
    response = consultant.post(f"{system}/plans/{plan_id}/write", json={})
    assert response.json()["detail"]["code"] == "uncovered_requirements"

    # 사람이 설계안을 고쳐 빠진 요건을 배정할 수 있다. 이름과 구성도 바꿀 수 있다.
    edited = _structure(procedure_codes=())
    edited["policies"][0]["title"] = "  소프트웨어 개발 정책  "
    procedure = edited["policies"][0]["procedures"][0]
    procedure["requirements"] = [CODES[2], "IEC99999 9.9-99"]  # 없는 코드는 버려진다
    procedure["instructions"].append(
        {"title": "개발 계획 검증 지침", "purpose": "", "requirements": [], "templates": []}
    )
    plan = consultant.put(f"{system}/plans/{plan_id}", json=edited).json()
    assert plan["uncovered"] == [] and plan["actions"] == ["write", "edit", "discard"]
    assert [(n["doc_type"], n["title"]) for n in plan["nodes"]] == [
        ("POL", "소프트웨어 개발 정책"),
        ("PRO", "개발 계획 절차"),
        ("WI", "개발 계획 수립 지침"),
        ("TMP", "개발 계획서"),
        ("WI", "개발 계획 검증 지침"),
    ]
    assert plan["nodes"][1]["requirements"] == [CODES[2]]
    # 제목이 비었거나 정책이 하나도 없는 설계안은 받지 않는다.
    blank = _structure()
    blank["policies"][0]["procedures"][0]["title"] = "  "
    assert consultant.put(f"{system}/plans/{plan_id}", json=blank).status_code == 422
    assert consultant.put(f"{system}/plans/{plan_id}", json={"policies": []}).status_code == 422
    # 요건을 빼면 다시 미배정이 된다.
    plan = consultant.put(f"{system}/plans/{plan_id}", json=_structure(procedure_codes=())).json()
    assert plan["uncovered"] == [CODES[2]]

    # 버리고 다시 설계할 수 있다.
    assert consultant.delete(f"{system}/plans/{plan_id}").status_code == 204
    assert consultant.get(f"{system}/plans").json() == []


def test_generation_requires_a_role_in_the_system(consultant, fake_pdf, monkeypatch):  # noqa: F811
    tenant = new_tenant(consultant)
    source_id, system = _approved_basis(consultant, tenant, monkeypatch)
    reviewer = add_member(consultant, tenant, "품질 책임자", ["qmr"])
    viewer = add_member(consultant, tenant, "구성원", [])

    start = {"source_ids": [source_id], "scope_code": "QMS"}
    assert viewer.post(f"{system}/plans", json=start).status_code == 403
    assert reviewer.post(f"{system}/plans", json=start).status_code == 403  # 검토 역할은 생성 불가
    assert viewer.get(f"{system}/basis").json()["actions"] == []
    # 품질 책임자는 적용요건 승인·취소를 할 수 있다.
    assert reviewer.post(f"{system}/basis/{source_id}/reopen").status_code == 200
    assert reviewer.post(f"{system}/basis/{source_id}/approve").status_code == 200
