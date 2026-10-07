"""초안을 기준으로 만드는 과정: 조직이 정할 항목 채우기, 여러 건 검토 요청·승인."""

import re
import uuid

from app import llm, worker
from app.pipelines.decide import Decided, DecideOutput
from tests.test_documents import _create, _fill, _team

OPEN = "정책은 〔조직 결정: 검토 주기〕마다 검토한다."


def _draft(client, tenant, doc_type, title, body="내용", **kwargs):
    detail = _create(client, tenant, doc_type, title, **kwargs).json()
    _fill(client, tenant, detail, body)
    return detail


def test_open_decisions_block_submission_until_filled(consultant):
    tenant, owner, qmr = _team(consultant)
    decisions = f"/api/t/{tenant}/systems/ims/decisions"
    pol = _draft(owner, tenant, "POL", "품질방침", OPEN, scope_code="QMS")
    revision_id = pol["open"]["id"]
    sections = len(pol["open"]["sections"])

    listed = owner.get(f"/api/t/{tenant}/systems/ims/documents").json()[0]
    assert listed["open_decisions"] == sections and listed["open_revision_id"] == revision_id

    # 정하지 않은 항목이 남은 문서는 기준이 될 수 없으므로 검토를 요청할 수 없다.
    blocked = owner.post(f"/api/t/{tenant}/revisions/{revision_id}/submit")
    assert blocked.status_code == 422 and blocked.json()["detail"]["code"] == "open_decisions"
    assert blocked.json()["detail"]["decisions"] == ["검토 주기"]

    groups = owner.get(decisions).json()
    assert [(g["label"], len(g["occurrences"])) for g in groups] == [("검토 주기", sections)]
    first = groups[0]["occurrences"][0]
    assert first["document"]["code"] == "POL-QMS-01"
    assert (first["before"], first["after"]) == ("정책은 ", "마다 검토한다.")

    fill = {"label": "검토 주기", "value": "연 1회"}
    assert qmr.post(decisions, json=fill).status_code == 403  # 검토 역할은 내용을 고칠 수 없다
    invalid = owner.post(decisions, json={"label": "검토 주기", "value": "〔나중에〕"})
    assert invalid.json()["detail"]["code"] == "invalid_value"

    # 한 곳만 채울 수도, 같은 이름의 항목을 모두 채울 수도 있다.
    target = {"revision_id": first["revision_id"], "section_key": first["section_key"]}
    one = owner.post(decisions, json={**fill, "targets": [target]}).json()
    assert one == {"places": 1, "documents": 1}
    rest = owner.post(decisions, json={"label": "검토 주기", "value": "반기"}).json()
    assert rest == {"places": sections - 1, "documents": 1}
    assert owner.get(decisions).json() == []
    again = owner.post(decisions, json=fill)
    assert again.json()["detail"]["code"] == "nothing_to_fill"

    revision = owner.get(f"/api/t/{tenant}/revisions/{revision_id}").json()
    assert revision["sections"][0]["body_md"] == "정책은 연 1회마다 검토한다."
    assert revision["sections"][1]["body_md"] == "정책은 반기마다 검토한다."
    # 누가 무엇을 정했는지 개정판과 감사 기록에 남는다.
    decided = revision["structured"]["decisions"]
    assert len(decided) == sections
    assert (decided[0]["label"], decided[0]["value"]) == ("검토 주기", "연 1회")
    assert decided[0]["section_key"] == first["section_key"] and decided[0]["decided_by"]
    log = consultant.get(f"/api/t/{tenant}/audit-log").json()["entries"]
    fills = [e for e in log if e["action"] == "decision.fill"]
    assert [e["data"]["places"] for e in fills] == [sections - 1, 1]
    assert fills[0]["data"]["documents"] == ["POL-QMS-01"]

    assert owner.post(f"/api/t/{tenant}/revisions/{revision_id}/submit").status_code == 200
    # 검토 중인 개정판은 고칠 수 없으니 채울 대상에서도 빠진다.
    assert owner.get(f"/api/t/{tenant}/systems/ims/documents").json()[0]["open_decisions"] == 0


def test_batch_submit_and_approve(consultant):
    tenant, owner, qmr = _team(consultant)
    batch = f"/api/t/{tenant}/review-batch"
    pol = _draft(owner, tenant, "POL", "품질방침", scope_code="QMS")
    pro = _draft(owner, tenant, "PRO", "문서 관리 절차", parent_id=pol["document"]["id"])
    wi = _draft(owner, tenant, "WI", "개정 지침", OPEN, parent_id=pro["document"]["id"])
    pol_id, pro_id, wi_id = (d["open"]["id"] for d in (pol, pro, wi))

    # 검토 역할만 있는 사람은 검토를 요청할 수 없다.
    refused = qmr.post(batch, json={"action": "submit", "revision_ids": [pol_id]}).json()
    assert refused["done"] == 0 and "권한" in refused["results"][0]["error"]

    # 안 되는 건은 사유와 함께 남기고 나머지는 처리한다.
    missing = str(uuid.uuid4())
    submitted = owner.post(
        batch, json={"action": "submit", "revision_ids": [wi_id, pro_id, pol_id, missing]}
    ).json()
    assert (submitted["done"], submitted["failed"]) == (2, 2)
    errors = {r["revision_id"]: r["error"] for r in submitted["results"] if not r["ok"]}
    assert "조직이 정해야 할 항목" in errors[wi_id] and "찾을 수 없습니다" in errors[missing]

    # 작성자는 자기 문서를 승인할 수 없다(한 건씩 할 때와 같은 규칙).
    own = owner.post(batch, json={"action": "approve", "revision_ids": [pol_id, pro_id]}).json()
    assert own["done"] == 0 and own["failed"] == 2

    # 하위 문서를 먼저 넘겨도 상위부터 승인한다.
    approved = qmr.post(
        batch, json={"action": "approve", "revision_ids": [pro_id, pol_id], "comment": "일괄 검토"}
    ).json()
    assert (approved["done"], approved["failed"]) == (2, 0)
    assert [r["document"]["code"] for r in approved["results"]] == ["POL-QMS-01", "PRO-QMS-01-01"]

    by_code = {d["code"]: d for d in owner.get(f"/api/t/{tenant}/systems/ims/documents").json()}
    assert by_code["POL-QMS-01"]["approved_version"] == "1.0"
    assert by_code["PRO-QMS-01-01"]["approved_version"] == "1.0"
    assert by_code["WI-QMS-01-01-01"]["open_status"] == "draft"
    revision = owner.get(f"/api/t/{tenant}/revisions/{pro_id}").json()
    assert (
        revision["reviewer"]["name"] == "품질 책임자" and revision["review_comment"] == "일괄 검토"
    )
    # 건마다 감사 기록이 남는다.
    log = consultant.get(f"/api/t/{tenant}/audit-log").json()["entries"]
    assert [e["action"] for e in log[:2]] == ["revision.approve", "revision.approve"]


TWO = "변경은 〔조직 결정: 승인권자〕가 승인하고, 기록은 〔조직 결정: 보존 기간〕 보관한다."


def test_ai_fills_open_decisions_and_marks_them(consultant, monkeypatch):
    tenant, owner, qmr = _team(consultant)
    decisions = f"/api/t/{tenant}/systems/ims/decisions"
    pol = _draft(owner, tenant, "POL", "품질방침", TWO, scope_code="QMS")
    # 사람이 이미 정한 값은 모델에 보여줘서 일관되게 쓰게 한다.
    owner.post(
        decisions,
        json={
            "label": "보존 기간",
            "value": "10년",
            "targets": [
                {"revision_id": pol["open"]["id"], "section_key": pol["open"]["sections"][0]["key"]}
            ],
        },
    )
    prompts: list[str] = []

    def structured(*, system, user, schema, **_):
        prompts.append(user)
        ids = re.findall(r"^- id: (\S+)\n  항목: (.+)$", user, re.MULTILINE)
        values = {"승인권자": "품질 책임자", "보존 기간": "〔10년〕"}
        items = [Decided(id=i, value=values[label], rationale=f"{label} 근거") for i, label in ids]
        items.append(Decided(id="없는-자리", value="x", rationale=""))
        return llm.LLMResult(DecideOutput(items=items), "fake-model", 10, 10)

    monkeypatch.setattr(llm, "structured", structured)
    assert qmr.post(f"{decisions}/ai").status_code == 403
    started = owner.post(f"{decisions}/ai").json()
    assert started["run"]["status"] == "queued"
    assert owner.post(f"{decisions}/ai").json()["detail"]["code"] == "run_in_progress"
    assert worker.process_next_run()

    assert "- 보존 기간: 10년" in prompts[0] and "회사: " in prompts[0]
    assert owner.get(decisions).json() == []
    state = owner.get(f"{decisions}/ai").json()
    assert state["run"]["status"] == "succeeded" and state["run"]["progress"]["done"] == 9
    filled = state["filled"]
    assert {(f["label"], f["value"]) for f in filled} == {
        ("승인권자", "품질 책임자"),
        ("보존 기간", "10년"),
    }
    assert filled[0]["document"]["code"] == "POL-QMS-01" and filled[0]["rationale"].endswith("근거")
    revision = owner.get(f"/api/t/{tenant}/revisions/{pol['open']['id']}").json()
    assert (
        revision["sections"][1]["body_md"] == "변경은 품질 책임자가 승인하고, 기록은 10년 보관한다."
    )
    record = next(d for d in revision["structured"]["decisions"] if d.get("by") == "ai")
    assert record["model"] == "fake-model" and record["decided_by"] is None
    log = [e["action"] for e in consultant.get(f"/api/t/{tenant}/audit-log").json()["entries"]]
    assert log[0] == "decision.ai_filled" and "decision.ai_fill" in log
    assert owner.post(f"{decisions}/ai").json()["detail"]["code"] == "nothing_to_fill"


def test_drafts_can_be_approved_without_a_review_request(consultant):
    tenant, owner, qmr = _team(consultant)
    batch = f"/api/t/{tenant}/review-batch"
    pol = _draft(owner, tenant, "POL", "품질방침", scope_code="QMS")
    pro = _draft(owner, tenant, "PRO", "문서 관리 절차", parent_id=pol["document"]["id"])
    wi = _draft(owner, tenant, "WI", "개정 지침", OPEN, parent_id=pro["document"]["id"])
    ids = [wi["open"]["id"], pro["open"]["id"], pol["open"]["id"]]

    # 검토만 할 수 있는 사람은 검토 요청 단계를 건너뛸 수 없다(요청 권한이 없다).
    refused = qmr.post(batch, json={"action": "approve_draft", "revision_ids": ids}).json()
    assert refused["done"] == 0 and "권한" in refused["results"][0]["error"]
    # 작성자는 자기 문서를 승인할 수 없다(검토 요청을 건너뛰어도 같다).
    own = owner.post(batch, json={"action": "approve_draft", "revision_ids": ids}).json()
    assert own["done"] == 0
    assert any("작성자" in r["error"] for r in own["results"])
    # 초안은 그대로 남는다(검토 요청 상태로 바뀌지 않는다).
    assert owner.get(f"/api/t/{tenant}/revisions/{pol['open']['id']}").json()["status"] == "draft"

    approved = consultant.post(
        batch, json={"action": "approve_draft", "revision_ids": ids, "comment": "일괄 승인"}
    ).json()
    assert (approved["done"], approved["failed"]) == (2, 1)
    errors = {r["revision_id"]: r["error"] for r in approved["results"] if not r["ok"]}
    assert "조직이 정해야 할 항목" in errors[wi["open"]["id"]]
    revision = owner.get(f"/api/t/{tenant}/revisions/{pro['open']['id']}").json()
    assert revision["status"] == "approved" and revision["review_comment"] == "일괄 승인"
    entries = consultant.get(f"/api/t/{tenant}/audit-log").json()["entries"]
    approvals = [e for e in entries if e["action"] == "revision.approve"]
    assert len(approvals) == 2 and all(e["data"]["skipped_review"] for e in approvals)
    assert [e["action"] for e in entries[:4]] == [
        "revision.approve",
        "revision.submit",
        "revision.approve",
        "revision.submit",
    ]
