"""초안을 기준으로 만드는 과정: 조직이 정할 항목 채우기, 여러 건 검토 요청·승인."""

import uuid

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
