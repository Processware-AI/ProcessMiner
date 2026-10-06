"""원문 등록 → 조항 분석 → 요건 도출 → 검토 → 확정.

PDF 읽기와 모델 호출은 가짜로 바꾼다. 여기서 확인하는 것은 그 사이의 규칙이다:
조항 분할, 인용 대조, 근거 없는 요건의 확정 차단, 실패한 절의 재시도.
"""

import pytest

from app import llm, worker
from app.extract.pdf import PageText, _strip_running_lines
from app.extract.structure import clean_title, segment_clauses
from app.pipelines import mining
from app.pipelines.mining import MinedRequirement, MiningOutput
from tests.conftest import add_member, new_tenant

PAGES = [
    # 목차: 조항으로 잡히면 안 된다.
    "Contents\n1 Scope ........ 2\n2 Requirements ........ 2\n2.1 Planning ........ 2",
    "1 Scope\nThis document applies to the development of software.\n"
    "2 Requirements\n2.1 Planning\n2.1.1 Development plan\n"
    "The MANUFACTURER  shall establish a development plan. The plan shall address:\n"
    "a) the processes to be used; and\nb) the deliverables.\n"
    "NOTE  A plan may be split into several documents.\n"
    "2.1.2 Keep plan updated\nThe manufacturer shall update the plan as development proceeds.",
    # 본문 속 번호(2.1 and 2.2)는 조항 제목이 아니다.
    "2.2 Verification\n2.1 and 2.2 are verified together in most projects.\n"
    "The manufacturer should verify the plan before use.\n"
    "Annex A\n(informative)\nRationale\nA.1 General\nThis annex shall not add requirements.",
]


def _pages():
    return [PageText(page_no=i, text=t, sparse=False) for i, t in enumerate(PAGES, start=1)]


# ── 추출과 조항 분할 ─────────────────────────────────────────────────────────


def test_running_headers_and_footers_are_removed():
    words = ["scope", "terms", "planning", "design", "testing", "release", "upkeep", "risk"]
    pages = [
        [f"– {n} – IEC 99999:2020", f"This page is about {word}.", "© IEC 2020"]
        for n, word in enumerate(words, start=1)
    ]
    cleaned = _strip_running_lines(pages)
    # 쪽 번호만 다른 머리말과 매 쪽 같은 꼬리말은 빠지고 본문만 남는다.
    assert cleaned == [[f"This page is about {word}."] for word in words]


def test_clauses_are_segmented_without_table_of_contents_or_inline_numbers():
    clauses = segment_clauses(_pages())
    assert [c.number for c in clauses] == [
        "1",
        "2",
        "2.1",
        "2.1.1",
        "2.1.2",
        "2.2",
        "Annex A",
        "A.1",
    ]
    by_number = {c.number: c for c in clauses}
    assert by_number["2.1.1"].title == "Development plan"
    assert by_number["2.1.1"].page_start == 2 and by_number["2.1.1"].parent_number == "2.1"
    # 본문 속의 "2.1 and 2.2 …" 문장은 2.2 조항의 본문으로 남는다.
    assert "verified together" in by_number["2.2"].text
    assert by_number["Annex A"].title == "Rationale" and not by_number["Annex A"].normative
    assert by_number["A.1"].kind == "annex" and by_number["A.1"].parent_number == "Annex A"


def test_titles_lose_extraction_artifacts_but_keep_real_one_letter_words():
    assert clean_title("R ISK MANAGEMENT  ACTIVITIES") == "RISK MANAGEMENT ACTIVITIES"
    assert clean_title("S oftware maintenance PROCESS") == "Software maintenance PROCESS"
    assert clean_title("Establish a plan") == "Establish a plan"
    assert clean_title("Select A PLAN") == "Select A PLAN"  # 관사 A 는 붙이지 않는다
    assert (
        clean_title("Evaluate REPORT ’S affect on SAFETY") == "Evaluate REPORT ’S affect on SAFETY"
    )


def test_units_cover_only_normative_clauses_with_obligations():
    units = mining.build_units(segment_clauses(_pages()))
    # 1절(범위)에는 의무 표현이 없고, 부속서는 참고용이라 빠진다.
    assert [u.number for u in units] == ["2.1", "2.2"]
    assert [c.number for c in units[0].clauses] == ["2.1", "2.1.1", "2.1.2"]


def test_quote_must_exist_in_the_clause():
    unit = mining.build_units(segment_clauses(_pages()))[0]
    output = MiningOutput(
        requirements=[
            # 추출 과정의 띄어쓰기 차이는 무시한다.
            _mined("2.1.1", "The MANUFACTURER shall establish a development plan."),
            # 조항 번호를 틀리게 적어도 같은 절 안에서 찾아 바로잡는다.
            _mined("2.1.1", "The manufacturer shall update the plan as development proceeds."),
            # 원문에 없는 문장은 근거 없음이다.
            _mined("2.1.1", "The manufacturer shall review the plan every quarter."),
        ]
    )
    results = mining.verify(unit, output)
    assert [(r.verified, r.clause_number) for r in results] == [
        (True, "2.1.1"),
        (True, "2.1.2"),
        (False, None),
    ]


def _mined(clause, quote, obligation="shall"):
    return MinedRequirement(
        clause=clause,
        quote=quote,
        obligation=obligation,
        summary="요약",
        category="documentation",
        applicability="",
        evidence=["개발 계획서"],
    )


# ── API 흐름 ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_pdf(monkeypatch):
    monkeypatch.setattr("app.services.sources.extract_pages", lambda data: _pages())


def _fake_llm(monkeypatch, answers, fail_units=()):
    """절 번호 → 모델이 돌려줄 요건 목록. fail_units 의 절은 호출이 실패한다."""

    def structured(*, system, user, schema, **_):
        unit = next(number for number in answers if f"### {number} " in user)
        if unit in fail_units:
            raise llm.LLMError("호출 한도를 넘었습니다. 잠시 후 다시 시도하세요.")
        return llm.LLMResult(
            output=MiningOutput(requirements=answers[unit]),
            model="fake-model",
            input_tokens=100,
            output_tokens=50,
        )

    monkeypatch.setattr(llm, "structured", structured)


def _upload(client, tenant, data=b"%PDF-1.7 fake"):
    return client.post(
        f"/api/t/{tenant}/sources",
        files={"file": ("standard.pdf", data, "application/pdf")},
        data={"title": "시험용 표준", "code": "iec99999", "edition": "2020"},
    )


ANSWERS = {
    "2.1": [
        _mined("2.1.1", "The MANUFACTURER shall establish a development plan."),
        _mined("2.1.2", "The manufacturer shall update the plan as development proceeds."),
        _mined("2.1.1", "The manufacturer shall review the plan every quarter."),  # 지어낸 문장
    ],
    "2.2": [_mined("2.2", "The manufacturer should verify the plan before use.", "should")],
}


def test_upload_extracts_clauses_immediately(consultant, fake_pdf):
    tenant = new_tenant(consultant)
    response = _upload(consultant, tenant)
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["status"] == "extracted" and source["code"] == "IEC99999"
    assert source["clause_count"] == 8 and source["obligation_clause_count"] == 3
    assert source["actions"] == ["mine", "delete"]

    clauses = consultant.get(f"/api/t/{tenant}/sources/{source['id']}/clauses").json()
    assert [c["number"] for c in clauses][:4] == ["1", "2", "2.1", "2.1.1"]
    detail = consultant.get(f"/api/t/{tenant}/clauses/{clauses[3]['id']}").json()
    assert "shall establish a development plan" in detail["text"]

    # 같은 파일은 다시 올릴 수 없고, PDF 가 아니면 받지 않는다.
    assert _upload(consultant, tenant).json()["detail"]["code"] == "duplicate_source"
    assert _upload(consultant, tenant, b"not a pdf").json()["detail"]["code"] == "unsupported_file"


def test_mining_review_and_confirm(consultant, fake_pdf, monkeypatch):
    tenant = new_tenant(consultant)
    source_id = _upload(consultant, tenant).json()["id"]
    base = f"/api/t/{tenant}/sources/{source_id}"
    _fake_llm(monkeypatch, ANSWERS)

    queued = consultant.post(f"{base}/mine").json()
    assert queued["status"] == "mining" and queued["run"]["status"] == "queued"
    assert queued["actions"] == []  # 도출 중에는 아무것도 할 수 없다
    assert consultant.post(f"{base}/mine").json()["detail"]["code"] == "run_in_progress"

    assert worker.process_next_run() is True
    assert worker.process_next_run() is False

    mined = consultant.get(base).json()
    assert mined["status"] == "mined" and mined["run"]["status"] == "succeeded"
    assert mined["run"]["progress"] == {
        "done": 2,
        "failed": 0,
        "total": 2,
        "input_tokens": 200,
        "output_tokens": 100,
    }
    assert mined["requirements"] == {"proposed": 4, "confirmed": 0, "rejected": 0, "unverified": 1}
    assert mined["actions"] == ["review", "confirm", "delete"]

    requirements = consultant.get(f"{base}/requirements").json()
    assert [r["code"] for r in requirements] == ["2.1.1-01", "2.1.1-02", "2.1.2-01", "2.2-01"]
    assert all(r["generated_by"] == "fake-model" for r in requirements)
    invented = next(r for r in requirements if not r["quote_verified"])
    assert invented["quote"].endswith("every quarter.")

    # 근거 없는 요건이 남아 있으면 확정할 수 없다.
    response = consultant.post(f"{base}/confirm")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "unverified_requirements"

    patch = f"/api/t/{tenant}/requirements"
    assert (
        consultant.patch(f"{patch}/{invented['id']}", json={"status": "rejected"}).json()["status"]
        == "rejected"
    )
    edited = consultant.patch(
        f"{patch}/{requirements[0]['id']}", json={"summary": "개발 계획을 수립한다."}
    ).json()
    assert edited["summary"] == "개발 계획을 수립한다."

    confirmed = consultant.post(f"{base}/confirm").json()
    assert confirmed["status"] == "confirmed" and confirmed["actions"] == []
    assert confirmed["requirements"] == {
        "proposed": 0,
        "confirmed": 3,
        "rejected": 1,
        "unverified": 0,
    }
    assert confirmed["confirmed_by"]["name"] == "컨설턴트"

    # 확정한 뒤에는 요건도 원문도 바꿀 수 없다.
    assert consultant.patch(f"{patch}/{edited['id']}", json={"summary": "x"}).status_code == 409
    assert consultant.delete(base).status_code == 409
    assert consultant.post(f"{base}/mine").status_code == 409


def test_failed_units_are_retried_without_repeating_finished_ones(
    consultant, fake_pdf, monkeypatch
):
    tenant = new_tenant(consultant)
    source_id = _upload(consultant, tenant).json()["id"]
    base = f"/api/t/{tenant}/sources/{source_id}"

    _fake_llm(monkeypatch, ANSWERS, fail_units={"2.2"})
    consultant.post(f"{base}/mine")
    worker.process_next_run()
    partial = consultant.get(base).json()
    assert partial["failed_units"] == ["2.2"] and partial["run"]["progress"]["failed"] == 1
    assert "mine" in partial["actions"]
    assert consultant.post(f"{base}/confirm").json()["detail"]["code"] == "unverified_requirements"

    calls = []
    original = ANSWERS

    def structured(*, system, user, schema, **_):
        calls.append(user)
        return llm.LLMResult(
            output=MiningOutput(requirements=original["2.2"]),
            model="fake-model",
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr(llm, "structured", structured)
    consultant.post(f"{base}/mine")
    worker.process_next_run()
    retried = consultant.get(base).json()
    # 끝난 2.1절은 다시 부르지 않고, 실패했던 2.2절만 처리한다.
    assert len(calls) == 1 and "### 2.2 " in calls[0]
    assert retried["failed_units"] == [] and retried["requirements"]["proposed"] == 4


def test_only_admins_manage_sources_and_tenants_are_isolated(consultant, fake_pdf):
    tenant = new_tenant(consultant)
    source_id = _upload(consultant, tenant).json()["id"]
    member = add_member(consultant, tenant, "구성원", ["process_owner"])

    assert member.get(f"/api/t/{tenant}/sources/{source_id}").json()["actions"] == []
    assert member.post(f"/api/t/{tenant}/sources/{source_id}/mine").status_code == 403
    assert _upload(member, tenant, b"%PDF-1.7 other").status_code == 403

    other = new_tenant(consultant)
    assert consultant.get(f"/api/t/{other}/sources").json() == []
    assert consultant.get(f"/api/t/{other}/sources/{source_id}").status_code == 404
