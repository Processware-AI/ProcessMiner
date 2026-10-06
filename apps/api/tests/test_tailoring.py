"""S3 완료 기준: 조직 한 곳이 문서 일부만 바꾼 체계를 갖고, 기준선 개정이 반영·표시된다."""

from tests.conftest import add_member, login, make_user, new_system, new_tenant
from tests.test_documents import _approve, _create


def _baseline(consultant):
    """기준선 체계(ims)에 승인된 정책 → 절차 → 지침 둘, 그리고 그 하위 체계(dev)."""
    tenant = new_tenant(consultant)
    base = new_system(consultant, tenant)
    new_system(consultant, tenant, slug="dev", parent_id=base["id"])
    owner = add_member(consultant, tenant, "프로세스 오너", ["process_owner"])
    qmr = add_member(consultant, tenant, "품질 책임자", ["qmr"])

    def approved(doc_type, title, **kwargs):
        detail = _create(owner, tenant, doc_type, title, **kwargs).json()
        _approve(owner, qmr, tenant, detail)
        return detail["document"]["id"]

    pol = approved("POL", "품질방침", scope_code="QMS")
    pro = approved("PRO", "문서 관리 절차", parent_id=pol)
    wi = approved("WI", "개정 지침", parent_id=pro)
    wi2 = approved("WI", "배포 지침", parent_id=pro)
    return tenant, owner, qmr, {"pol": pol, "pro": pro, "wi": wi, "wi2": wi2}


def _listing(client, tenant, system="dev"):
    return client.get(f"/api/t/{tenant}/systems/{system}/documents").json()


def _revise(owner, qmr, tenant, document_id, body):
    """기준선 문서를 경미 개정해 승인까지 한다."""
    revision = owner.post(
        f"/api/t/{tenant}/documents/{document_id}/revisions",
        json={"change_kind": "minor", "change_summary": "보완"},
    ).json()
    sections = [{**s, "body_md": body} for s in revision["sections"]]
    path = f"/api/t/{tenant}/revisions/{revision['id']}"
    assert owner.patch(path, json={"sections": sections}).status_code == 200
    assert owner.post(f"{path}/submit").status_code == 200
    assert qmr.post(f"{path}/approve", json={}).status_code == 200


def test_child_system_inherits_documents_and_follows_revisions(consultant):
    tenant, owner, qmr, ids = _baseline(consultant)

    dev = _listing(owner, tenant)
    assert [(d["code"], d["tailoring"], d["home_system_slug"]) for d in dev] == [
        ("POL-QMS-01", "inherited", "ims"),
        ("PRO-QMS-01-01", "inherited", "ims"),
        ("WI-QMS-01-01-01", "inherited", "ims"),
        ("WI-QMS-01-01-02", "inherited", "ims"),
    ]
    assert dev[2]["parent_id"] == ids["pro"] and dev[2]["approved_version"] == "1.0"
    assert {d["tailoring"] for d in _listing(owner, tenant, "ims")} == {"own"}

    # 기준선에서 진행 중인 개정은 내려오지 않고, 승인되면 그대로 따라간다.
    draft = owner.post(
        f"/api/t/{tenant}/documents/{ids['wi2']}/revisions", json={"change_kind": "minor"}
    ).json()
    inherited = _listing(owner, tenant)[3]
    assert inherited["open_status"] is None and inherited["approved_version"] == "1.0"
    detail = owner.get(f"/api/t/{tenant}/documents/{ids['wi2']}?system=dev").json()
    assert detail["open"] is None and detail["tailoring"]["state"] == "inherited"
    assert detail["tailoring"]["home_system"]["slug"] == "ims"
    # 하위 체계에서 볼 때는 기준선 문서를 고칠 수 없고, 테일러링만 할 수 있다.
    assert detail["actions"] == ["create_child:TMP", "create_child:EX"]
    assert detail["tailoring"]["actions"] == ["override", "exclude"]
    owner.delete(f"/api/t/{tenant}/revisions/{draft['id']}")
    _revise(owner, qmr, tenant, ids["wi2"], "보완한 내용")
    assert _listing(owner, tenant)[3]["approved_version"] == "1.1"


def test_override_starts_from_the_parent_and_shows_when_the_parent_changes(consultant):
    tenant, owner, qmr, ids = _baseline(consultant)
    target = f"/api/t/{tenant}/systems/dev/tailoring/{ids['wi']}"

    assert qmr.post(f"{target}/override", json={"reason": "사유"}).status_code == 403
    missing = owner.post(f"{target}/override", json={})
    assert missing.json()["detail"]["code"] == "reason_required"
    # 기준선 체계 자신의 문서는 테일러링 대상이 아니다.
    own = owner.post(
        f"/api/t/{tenant}/systems/ims/tailoring/{ids['wi']}/override", json={"reason": "사유"}
    )
    assert own.json()["detail"]["code"] == "baseline_system"

    created = owner.post(f"{target}/override", json={"reason": "개발본부는 코드 리뷰 도구를 쓴다"})
    assert created.status_code == 201, created.text
    override = created.json()
    override_id = override["document"]["id"]
    # 같은 번호의 문서가 이 체계에 생기고, 상위 승인판의 내용에서 시작한다.
    assert override["document"]["code"] == "WI-QMS-01-01-01"
    assert override["document"]["tailoring"] == "override"
    assert override["system"]["slug"] == "dev" and override["open"]["status"] == "draft"
    assert override["open"]["sections"][0]["body_md"] == "내용"
    assert "v1.0 에서 재정의" in override["open"]["change_summary"]
    info = override["tailoring"]
    assert info["base"]["id"] == ids["wi"] and info["base_system"]["slug"] == "ims"
    assert info["reason"] == "개발본부는 코드 리뷰 도구를 쓴다" and not info["base_changed"]
    assert [a["code"] for a in override["ancestors"]] == ["POL-QMS-01", "PRO-QMS-01-01"]
    assert owner.post(f"{target}/override", json={"reason": "다시"}).status_code == 404

    dev = {d["code"]: d for d in _listing(owner, tenant)}
    assert len(dev) == 4  # 상위 문서 자리를 대체했으므로 문서 수는 그대로다
    assert dev["WI-QMS-01-01-01"]["id"] == override_id
    assert dev["WI-QMS-01-01-01"]["parent_id"] == ids["pro"]
    assert dev["WI-QMS-01-01-01"]["base_document_id"] == ids["wi"]
    # 기준선은 그대로다.
    ims = {d["code"]: d for d in _listing(owner, tenant, "ims")}
    assert ims["WI-QMS-01-01-01"]["id"] == ids["wi"]

    # 재정의한 문서는 이 체계에서 보통 문서처럼 고치고 승인받는다.
    revision = f"/api/t/{tenant}/revisions/{override['open']['id']}"
    sections = [{**s, "body_md": "개발본부 내용"} for s in override["open"]["sections"]]
    assert owner.patch(revision, json={"sections": sections}).status_code == 200
    assert owner.post(f"{revision}/submit").status_code == 200
    assert qmr.post(f"{revision}/approve", json={}).status_code == 200

    # 기준선 문서가 개정되면 재정의한 문서에 '상위 변경됨'이 표시된다.
    _revise(owner, qmr, tenant, ids["wi"], "기준선 보완")
    assert {d["code"]: d for d in _listing(owner, tenant)}["WI-QMS-01-01-01"]["base_changed"]
    detail = owner.get(f"/api/t/{tenant}/documents/{override_id}?system=dev").json()
    info = detail["tailoring"]
    assert info["base_changed"] and info["actions"] == ["ack_base"]
    assert (info["base_forked"]["version"], info["base_current"]["version"]) == ("1.0", "1.1")
    assert detail["approved"]["sections"][0]["body_md"] == "개발본부 내용"  # 내용은 그대로다

    # 변경을 확인하면(반영했거나 반영하지 않기로 했거나) 표시가 사라진다.
    acknowledged = owner.post(f"/api/t/{tenant}/documents/{override_id}/ack-base").json()
    assert not acknowledged["tailoring"]["base_changed"]
    assert acknowledged["tailoring"]["base_forked"]["version"] == "1.1"
    again = owner.post(f"/api/t/{tenant}/documents/{override_id}/ack-base")
    assert again.json()["detail"]["code"] == "base_unchanged"

    log = [e["action"] for e in consultant.get(f"/api/t/{tenant}/audit-log").json()["entries"]]
    assert "tailoring.override" in log and log[0] == "tailoring.sync"


def test_draft_override_can_be_discarded_back_to_inheritance(consultant):
    tenant, owner, _qmr, ids = _baseline(consultant)
    override = owner.post(
        f"/api/t/{tenant}/systems/dev/tailoring/{ids['wi']}/override", json={"reason": "시험"}
    ).json()
    assert owner.delete(f"/api/t/{tenant}/revisions/{override['open']['id']}").json() == {
        "document_deleted": True
    }
    dev = {d["code"]: d for d in _listing(owner, tenant)}
    assert dev["WI-QMS-01-01-01"]["tailoring"] == "inherited"
    assert dev["WI-QMS-01-01-01"]["id"] == ids["wi"]


def test_exclusion_and_added_documents(consultant):
    tenant, owner, qmr, ids = _baseline(consultant)
    exclusion = f"/api/t/{tenant}/systems/dev/tailoring/{ids['wi2']}/exclusion"

    assert qmr.put(exclusion, json={"reason": "사유"}).status_code == 403
    assert owner.put(exclusion, json={}).json()["detail"]["code"] == "reason_required"
    assert owner.put(exclusion, json={"reason": "배포는 운영팀이 한다"}).status_code == 204

    dev = {d["code"]: d for d in _listing(owner, tenant)}
    excluded = dev["WI-QMS-01-01-02"]
    assert (excluded["tailoring"], excluded["tailoring_reason"]) == (
        "excluded",
        "배포는 운영팀이 한다",
    )
    detail = owner.get(f"/api/t/{tenant}/documents/{ids['wi2']}?system=dev").json()
    assert detail["tailoring"]["state"] == "excluded" and detail["actions"] == []
    assert detail["tailoring"]["actions"] == ["include"]
    # 제외한 문서 아래에는 문서를 추가할 수 없다.
    refused = _create(owner, tenant, "TMP", "배포 점검표", parent_id=ids["wi2"], system="dev")
    assert refused.json()["detail"]["code"] == "parent_not_found"

    # 제외를 되돌리면 다시 상위 문서를 그대로 쓴다.
    assert owner.delete(exclusion).status_code == 204
    assert _listing(owner, tenant)[3]["tailoring"] == "inherited"

    # 물려받은 문서 아래에 이 체계만의 문서를 추가할 수 있다. 번호는 계보 안에서 겹치지 않는다.
    added = _create(owner, tenant, "TMP", "개발본부 점검표", parent_id=ids["wi2"], system="dev")
    assert added.status_code == 201, added.text
    assert added.json()["document"]["code"] == "TMP-QMS-01-01-02-01"
    assert added.json()["document"]["tailoring"] == "added"
    dev = {d["code"]: d for d in _listing(owner, tenant)}
    assert dev["TMP-QMS-01-01-02-01"]["parent_id"] == ids["wi2"]
    assert "TMP-QMS-01-01-02-01" not in {d["code"] for d in _listing(owner, tenant, "ims")}
    baseline_tmp = _create(owner, tenant, "TMP", "배포 기록", parent_id=ids["wi2"]).json()
    assert baseline_tmp["document"]["code"] == "TMP-QMS-01-01-02-02"

    # 이 체계가 추가하거나 재정의한 문서가 아래에 있으면, 그 위의 문서는 제외할 수 없다.
    blocked = owner.put(
        f"/api/t/{tenant}/systems/dev/tailoring/{ids['pro']}/exclusion", json={"reason": "사유"}
    )
    assert blocked.json()["detail"]["code"] == "has_own_documents"


def test_excluding_a_document_excludes_what_is_under_it_and_passes_down(consultant):
    tenant, owner, _qmr, ids = _baseline(consultant)
    dev_id = consultant.get(f"/api/t/{tenant}/systems/dev").json()["id"]
    new_system(consultant, tenant, slug="dev-a", parent_id=dev_id)

    override = owner.post(
        f"/api/t/{tenant}/systems/dev/tailoring/{ids['pol']}/override", json={"reason": "본부 방침"}
    ).json()
    assert (
        owner.put(
            f"/api/t/{tenant}/systems/dev/tailoring/{ids['pro']}/exclusion",
            json={"reason": "문서 관리는 전사 조직이 한다"},
        ).status_code
        == 204
    )
    dev = {d["code"]: d for d in _listing(owner, tenant)}
    # 절차를 제외하면 그 아래 지침도 함께 빠진다(따로 되돌릴 수는 없다).
    assert dev["WI-QMS-01-01-01"]["tailoring"] == "excluded"
    assert (
        dev["WI-QMS-01-01-01"]["tailoring_implied"]
        and not dev["PRO-QMS-01-01"]["tailoring_implied"]
    )
    under = owner.get(f"/api/t/{tenant}/documents/{ids['wi']}?system=dev").json()
    assert under["tailoring"]["implied"] and under["tailoring"]["actions"] == []

    # 그 아래 체계에는 본부가 재정의한 문서가 내려오고, 본부가 제외한 문서는 내려오지 않는다.
    team = _listing(owner, tenant, "dev-a")
    assert [(d["code"], d["tailoring"], d["home_system_slug"]) for d in team] == [
        ("POL-QMS-01", "inherited", "dev")
    ]
    assert team[0]["id"] == override["document"]["id"]


def test_company_with_tailoring_can_be_purged(consultant):
    tenant, owner, _qmr, ids = _baseline(consultant)
    base = f"/api/t/{tenant}/systems/dev/tailoring"
    assert owner.post(f"{base}/{ids['wi']}/override", json={"reason": "사유"}).status_code == 201
    assert owner.put(f"{base}/{ids['wi2']}/exclusion", json={"reason": "사유"}).status_code == 204

    admin = login(make_user("플랫폼 관리자", "platform_admin"))
    assert consultant.post(f"/api/t/{tenant}/archive").status_code == 200
    response = admin.post(f"/api/t/{tenant}/purge", json={"confirm_slug": tenant})
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["documents"] == 5
