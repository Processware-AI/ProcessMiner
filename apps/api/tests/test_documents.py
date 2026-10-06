"""S1 완료 기준: 손으로 POL→PRO→WI→TMP 를 만들고 개정·승인할 수 있다."""

from concurrent.futures import ThreadPoolExecutor

from tests.conftest import add_member, new_system, new_tenant


def _create(client, tenant, doc_type, title, parent_id=None, scope_code=None, system="ims"):
    return client.post(
        f"/api/t/{tenant}/systems/{system}/documents",
        json={
            "doc_type": doc_type,
            "title": title,
            "parent_id": parent_id,
            "scope_code": scope_code,
        },
    )


def _fill(client, tenant, detail, body="내용"):
    revision = detail["open"]
    sections = [{**s, "body_md": body} for s in revision["sections"]]
    response = client.patch(
        f"/api/t/{tenant}/revisions/{revision['id']}", json={"sections": sections}
    )
    assert response.status_code == 200, response.text
    return revision["id"]


def _approve(author, reviewer, tenant, detail):
    revision_id = _fill(author, tenant, detail)
    assert author.post(f"/api/t/{tenant}/revisions/{revision_id}/submit").status_code == 200
    response = reviewer.post(f"/api/t/{tenant}/revisions/{revision_id}/approve", json={})
    assert response.status_code == 200, response.text
    return response.json()


def _team(consultant):
    tenant = new_tenant(consultant)
    new_system(consultant, tenant)
    owner = add_member(consultant, tenant, "프로세스 오너", ["process_owner"])
    qmr = add_member(consultant, tenant, "품질 책임자", ["qmr"])
    return tenant, owner, qmr


def test_hierarchy_numbering_and_approval(consultant):
    tenant, owner, qmr = _team(consultant)

    pol = _create(owner, tenant, "POL", "품질방침", scope_code="QMS").json()
    assert pol["document"]["code"] == "POL-QMS-01"
    assert pol["open"]["version"] == "1.0" and pol["open"]["status"] == "draft"
    assert [s["key"] for s in pol["open"]["sections"]][:2] == ["purpose", "scope"]
    _approve(owner, qmr, tenant, pol)

    pro = _create(owner, tenant, "PRO", "문서 관리 절차", parent_id=pol["document"]["id"]).json()
    assert pro["document"]["code"] == "PRO-QMS-01-01"
    assert pro["document"]["scope_code"] == "QMS"  # 상위에서 물려받는다
    _approve(owner, qmr, tenant, pro)

    wi = _create(owner, tenant, "WI", "개정 지침", parent_id=pro["document"]["id"]).json()
    assert wi["document"]["code"] == "WI-QMS-01-01-01"
    _approve(owner, qmr, tenant, wi)

    tmp = _create(owner, tenant, "TMP", "개정 요청서", parent_id=wi["document"]["id"]).json()
    ex = _create(owner, tenant, "EX", "개정 요청서 예시", parent_id=wi["document"]["id"]).json()
    assert tmp["document"]["code"] == "TMP-QMS-01-01-01-01"
    assert ex["document"]["code"] == "EX-QMS-01-01-01-01"
    assert [a["code"] for a in tmp["ancestors"]] == [
        "POL-QMS-01",
        "PRO-QMS-01-01",
        "WI-QMS-01-01-01",
    ]

    second = _create(owner, tenant, "POL", "교육훈련 정책", scope_code="QMS").json()
    other_scope = _create(owner, tenant, "POL", "정보보안 정책", scope_code="ISMS").json()
    assert second["document"]["code"] == "POL-QMS-02"
    assert other_scope["document"]["code"] == "POL-ISMS-01"

    listing = owner.get(f"/api/t/{tenant}/systems/ims/documents").json()
    by_code = {d["code"]: d for d in listing}
    assert by_code["POL-QMS-01"]["approved_version"] == "1.0"
    assert by_code["TMP-QMS-01-01-01-01"]["open_status"] == "draft"


def test_hierarchy_rules_are_enforced(consultant):
    tenant, owner, _ = _team(consultant)
    pol = _create(owner, tenant, "POL", "정책", scope_code="QMS").json()["document"]["id"]

    assert _create(owner, tenant, "POL", "영역 없음").json()["detail"]["code"] == "scope_required"
    assert (
        _create(owner, tenant, "POL", "없는 영역", scope_code="ZZZ").json()["detail"]["code"]
        == "unknown_scope"
    )
    assert _create(owner, tenant, "PRO", "상위 없음").json()["detail"]["code"] == "parent_required"
    assert (
        _create(owner, tenant, "WI", "유형 건너뜀", parent_id=pol).json()["detail"]["code"]
        == "parent_type_mismatch"
    )
    assert _create(owner, tenant, "MAT", "관리대장").status_code == 422


def test_review_flow_with_rejection_and_four_eyes(consultant):
    tenant, owner, qmr = _team(consultant)
    pol = _create(owner, tenant, "POL", "정책", scope_code="QMS").json()
    revision_id = pol["open"]["id"]
    base = f"/api/t/{tenant}/revisions/{revision_id}"

    # 필수 섹션이 비어 있으면 제출할 수 없다.
    response = owner.post(f"{base}/submit")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "missing_sections"

    _fill(owner, tenant, pol)
    assert owner.post(f"{base}/submit").json()["status"] == "in_review"

    # 검토 중에는 편집할 수 없다.
    assert owner.patch(base, json={"title": "바꾼 제목"}).status_code == 409
    # 작성자는 검토 권한이 있어도 자기 개정판을 승인할 수 없다.
    assert owner.post(f"{base}/approve", json={}).json()["detail"]["code"] == "four_eyes"
    # 반려에는 사유가 필요하다.
    assert qmr.post(f"{base}/reject", json={}).json()["detail"]["code"] == "comment_required"

    rejected = qmr.post(f"{base}/reject", json={"comment": "범위를 구체적으로"}).json()
    assert rejected["status"] == "draft" and rejected["review_comment"] == "범위를 구체적으로"
    assert [i["kind"] for i in owner.get(f"/api/t/{tenant}/inbox").json()] == ["returned"]

    assert owner.post(f"{base}/submit").status_code == 200
    assert [i["kind"] for i in qmr.get(f"/api/t/{tenant}/inbox").json()] == ["to_review"]
    assert [i["kind"] for i in owner.get(f"/api/t/{tenant}/inbox").json()] == ["my_in_review"]

    approved = qmr.post(f"{base}/approve", json={"comment": "확인"}).json()
    assert approved["status"] == "approved" and approved["content_hash"]
    assert approved["reviewer"]["name"] == "품질 책임자"
    assert owner.get(f"/api/t/{tenant}/inbox").json() == []


def test_child_cannot_be_approved_before_its_parent(consultant):
    tenant, owner, qmr = _team(consultant)
    pol = _create(owner, tenant, "POL", "정책", scope_code="QMS").json()
    pro = _create(owner, tenant, "PRO", "절차", parent_id=pol["document"]["id"]).json()

    revision_id = _fill(owner, tenant, pro)
    assert owner.post(f"/api/t/{tenant}/revisions/{revision_id}/submit").status_code == 200
    response = qmr.post(f"/api/t/{tenant}/revisions/{revision_id}/approve", json={})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "parent_not_approved"


def test_revising_an_approved_document(consultant):
    tenant, owner, qmr = _team(consultant)
    pol = _create(owner, tenant, "POL", "정책", scope_code="QMS").json()
    document_id = pol["document"]["id"]
    first = _approve(owner, qmr, tenant, pol)
    revisions = f"/api/t/{tenant}/documents/{document_id}/revisions"

    draft = owner.post(revisions, json={"change_kind": "minor", "change_summary": "오탈자"}).json()
    assert draft["version"] == "1.1" and draft["sections"] == first["sections"]
    # 진행 중인 개정판은 하나뿐이다.
    assert owner.post(revisions, json={}).json()["detail"]["code"] == "revision_in_progress"

    # 개정 구분을 바꾸면 목표 버전도 바뀐다.
    patched = owner.patch(
        f"/api/t/{tenant}/revisions/{draft['id']}",
        json={"change_kind": "major", "title": "개정된 정책"},
    ).json()
    assert patched["version"] == "2.0"

    # 승인 전까지는 기존 승인판이 계속 유효하다.
    detail = owner.get(f"/api/t/{tenant}/documents/{document_id}").json()
    assert detail["approved"]["version"] == "1.0" and detail["document"]["title"] == "정책"

    assert owner.post(f"/api/t/{tenant}/revisions/{draft['id']}/submit").status_code == 200
    assert qmr.post(f"/api/t/{tenant}/revisions/{draft['id']}/approve", json={}).status_code == 200

    detail = owner.get(f"/api/t/{tenant}/documents/{document_id}").json()
    assert detail["approved"]["version"] == "2.0" and detail["document"]["title"] == "개정된 정책"
    assert detail["open"] is None
    history = owner.get(revisions).json()
    assert [(r["version"], r["status"]) for r in history] == [
        ("2.0", "approved"),
        ("1.0", "superseded"),
    ]


def test_discarding_drafts(consultant):
    tenant, owner, qmr = _team(consultant)
    pol = _create(owner, tenant, "POL", "정책", scope_code="QMS").json()
    pro = _create(owner, tenant, "PRO", "절차", parent_id=pol["document"]["id"]).json()

    # 하위 문서가 있는 미승인 문서는 지울 수 없다.
    response = owner.delete(f"/api/t/{tenant}/revisions/{pol['open']['id']}")
    assert response.json()["detail"]["code"] == "has_children"

    # 한 번도 승인되지 않은 문서의 초안을 버리면 문서도 사라진다.
    assert owner.delete(f"/api/t/{tenant}/revisions/{pro['open']['id']}").json() == {
        "document_deleted": True
    }
    assert owner.get(f"/api/t/{tenant}/documents/{pro['document']['id']}").status_code == 404

    # 승인판이 있는 문서의 개정 초안을 버리면 승인판은 남는다.
    _approve(owner, qmr, tenant, pol)
    document_id = pol["document"]["id"]
    draft = owner.post(f"/api/t/{tenant}/documents/{document_id}/revisions", json={}).json()
    assert owner.delete(f"/api/t/{tenant}/revisions/{draft['id']}").json() == {
        "document_deleted": False
    }
    assert (
        owner.get(f"/api/t/{tenant}/documents/{document_id}").json()["approved"]["version"] == "1.0"
    )


def test_permissions_on_documents(consultant):
    tenant, owner, qmr = _team(consultant)
    member = add_member(consultant, tenant, "일반 구성원", [])
    pol = _create(owner, tenant, "POL", "정책", scope_code="QMS").json()
    revision = f"/api/t/{tenant}/revisions/{pol['open']['id']}"

    assert member.get(f"/api/t/{tenant}/documents/{pol['document']['id']}").status_code == 200
    assert _create(member, tenant, "POL", "권한 없음", scope_code="QMS").status_code == 403
    assert member.patch(revision, json={"title": "x"}).status_code == 403
    assert qmr.patch(revision, json={"title": "x"}).status_code == 403  # 검토 역할은 편집 불가
    assert member.get(f"/api/t/{tenant}/audit-log").status_code == 403

    # 화면이 쓰는 행위 목록도 역할에 맞게 나온다.
    def actions(client):
        url = f"/api/t/{tenant}/documents/{pol['document']['id']}"
        return client.get(url).json()["actions"]

    assert {"edit", "submit", "discard", "create_child:PRO"} <= set(actions(owner))
    assert actions(member) == []


def test_concurrent_creation_never_duplicates_a_number(consultant):
    tenant, owner, _ = _team(consultant)

    def create(i):
        return _create(owner, tenant, "POL", f"정책 {i}", scope_code="QMS").json()["document"][
            "code"
        ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(create, range(16)))
    assert sorted(codes) == [f"POL-QMS-{n:02d}" for n in range(1, 17)]


def test_child_system_shares_the_numbering_of_its_lineage(consultant):
    tenant, owner, _ = _team(consultant)
    baseline = consultant.get(f"/api/t/{tenant}/systems/ims").json()
    new_system(consultant, tenant, slug="dev", parent_id=baseline["id"])

    first = _create(owner, tenant, "POL", "기준선 정책", scope_code="QMS").json()
    second = _create(owner, tenant, "POL", "조직 추가 정책", scope_code="QMS", system="dev").json()
    assert first["document"]["code"] == "POL-QMS-01"
    assert second["document"]["code"] == "POL-QMS-02"  # 계보 안에서 번호가 겹치지 않는다


def test_audit_log_records_actions_in_an_intact_chain(consultant, owner_engine):
    from sqlalchemy import text

    tenant, owner, qmr = _team(consultant)
    pol = _create(owner, tenant, "POL", "정책", scope_code="QMS").json()
    _approve(owner, qmr, tenant, pol)

    log = consultant.get(f"/api/t/{tenant}/audit-log").json()
    assert log["chain_intact"] is True
    actions = [e["action"] for e in reversed(log["entries"])]
    assert actions[0] == "tenant.create"
    assert actions[-3:] == ["document.create", "revision.submit", "revision.approve"]
    assert log["entries"][0]["actor"]["name"] == "품질 책임자"

    # 누군가 DB 에서 기록을 고치면 사슬 검증이 그 행을 짚어낸다.
    tampered_id = log["entries"][2]["id"]
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"), {"id": tampered_id}
        )
    log = consultant.get(f"/api/t/{tenant}/audit-log").json()
    assert log["chain_intact"] is False and log["broken_at"] == tampered_id
