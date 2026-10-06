"""적용요건 승인 → 문서 구조 설계 → 문서 생성.

모델 호출은 가짜로 바꾼다. 확인하는 것은 그 사이의 규칙이다: 승인 전에는 설계할 수 없고,
모든 적용요건이 문서에 배정돼야 하며, 근거가 맞지 않는 본문은 저장되지 않는다.
"""

import re

import pytest

from app import llm, worker
from app.pipelines import planning
from app.pipelines.planning import (
    DesignOutput,
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


def _fake_generation(monkeypatch, structure, bad_titles=()):
    """설계에는 structure 를, 문서 작성에는 근거 게이트를 통과하는 본문을 돌려준다.

    bad_titles 의 문서는 근거 없는 본문을 돌려준다(게이트에서 걸려야 한다).
    """

    def structured(*, system, user, schema, **_):
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
    assert plan["actions"] == ["write", "discard"]
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
    assert plan["uncovered"] == [CODES[2]] and plan["actions"] == ["discard"]
    response = consultant.post(f"{system}/plans/{plan_id}/write", json={})
    assert response.json()["detail"]["code"] == "uncovered_requirements"

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
