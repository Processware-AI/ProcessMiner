"""문서 정리(삭제·폐지·되살리기·위치 바꾸기·복사·옮기기)와 체계 관리(이름 바꾸기·삭제)."""

from sqlalchemy import text

from tests.conftest import add_member, new_system, new_tenant
from tests.test_documents import _approve, _create, _fill


def _setup(consultant):
    """기준선 체계 ims: 승인된 정책 → 승인된 절차 둘, 첫 절차 아래 승인된 지침과 초안 양식."""
    tenant = new_tenant(consultant)
    new_system(consultant, tenant)
    owner = add_member(consultant, tenant, "프로세스 오너", ["process_owner"])
    qmr = add_member(consultant, tenant, "품질 책임자", ["qmr"])

    def approved(doc_type, title, **kwargs):
        detail = _create(owner, tenant, doc_type, title, **kwargs).json()
        _approve(owner, qmr, tenant, detail)
        return detail["document"]["id"]

    pol = approved("POL", "품질방침", scope_code="QMS")
    pro = approved("PRO", "문서 관리 절차", parent_id=pol)
    pro2 = approved("PRO", "교육 절차", parent_id=pol)
    wi = approved("WI", "개정 지침", parent_id=pro)
    tmp = _create(owner, tenant, "TMP", "개정 요청서", parent_id=wi).json()
    _fill(owner, tenant, tmp, body="양식 본문")
    ids = {"pol": pol, "pro": pro, "pro2": pro2, "wi": wi, "tmp": tmp["document"]["id"]}
    return tenant, owner, qmr, ids


def _codes(client, tenant, system="ims"):
    return [d["code"] for d in client.get(f"/api/t/{tenant}/systems/{system}/documents").json()]


def test_remove_deletes_drafts_and_retires_approved_documents(consultant):
    tenant, owner, qmr, ids = _setup(consultant)
    remove = f"/api/t/{tenant}/documents/remove"

    # 검토자는 문서를 정리할 수 없다.
    assert qmr.post(remove, json={"document_ids": [ids["wi"]]}).status_code == 403

    # 미리 보기: 승인된 지침은 폐지, 초안뿐인 양식은 삭제. 아무것도 바뀌지 않는다.
    preview = owner.post(remove, json={"document_ids": [ids["wi"]], "dry_run": True}).json()
    assert [d["code"] for d in preview["retired"]] == ["WI-QMS-01-01-01"]
    assert [d["code"] for d in preview["deleted"]] == ["TMP-QMS-01-01-01-01"]
    assert "TMP-QMS-01-01-01-01" in _codes(owner, tenant)

    # 폐지되는 문서가 있으면 사유가 필요하다.
    missing = owner.post(remove, json={"document_ids": [ids["wi"]]})
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "reason_required"

    done = owner.post(remove, json={"document_ids": [ids["wi"]], "reason": "업무 통폐합"}).json()
    assert not done["dry_run"] and len(done["retired"]) == 1 and len(done["deleted"]) == 1
    assert _codes(owner, tenant) == ["POL-QMS-01", "PRO-QMS-01-01", "PRO-QMS-01-02"]
    assert owner.get(f"/api/t/{tenant}/documents/{ids['tmp']}").status_code == 404

    # 폐지한 문서는 이력과 함께 남고, 되살리기 전에는 개정할 수 없다.
    retired = owner.get(f"/api/t/{tenant}/systems/ims/documents/retired").json()
    assert [(d["code"], d["retire_reason"]) for d in retired] == [
        ("WI-QMS-01-01-01", "업무 통폐합")
    ]
    detail = owner.get(f"/api/t/{tenant}/documents/{ids['wi']}").json()
    assert detail["document"]["retired_at"] and detail["approved"]["version"] == "1.0"
    assert detail["actions"] == ["restore"]
    assert [a["code"] for a in detail["ancestors"]] == ["POL-QMS-01", "PRO-QMS-01-01"]
    revise = owner.post(
        f"/api/t/{tenant}/documents/{ids['wi']}/revisions", json={"change_kind": "minor"}
    )
    assert revise.json()["detail"]["code"] == "document_retired"
    # 폐지한 문서 아래에는 새 문서를 만들 수 없다.
    under = _create(owner, tenant, "TMP", "새 양식", parent_id=ids["wi"])
    assert under.json()["detail"]["code"] == "parent_not_found"

    restored = owner.post(f"/api/t/{tenant}/documents/{ids['wi']}/restore").json()
    assert [d["code"] for d in restored["restored"]] == ["WI-QMS-01-01-01"]
    assert "WI-QMS-01-01-01" in _codes(owner, tenant)


def test_removing_a_parent_retires_it_when_a_child_must_stay(consultant):
    tenant, owner, qmr, ids = _setup(consultant)

    # 정책을 정리하면 그 아래 문서가 모두 함께 정리된다. 승인 이력이 있는 문서는 폐지된다.
    done = owner.post(
        f"/api/t/{tenant}/documents/remove",
        json={"document_ids": [ids["pol"]], "reason": "체계 재편"},
    ).json()
    assert {d["code"] for d in done["retired"]} == {
        "POL-QMS-01",
        "PRO-QMS-01-01",
        "PRO-QMS-01-02",
        "WI-QMS-01-01-01",
    }
    assert _codes(owner, tenant) == []

    # 하위 문서를 먼저 되살릴 수는 없다. 정책을 되살리면 함께 폐지된 문서가 모두 돌아온다.
    # 상위 문서까지 폐지된 문서도 열린다(계층은 폐지되지 않은 상위까지만).
    detail = owner.get(f"/api/t/{tenant}/documents/{ids['wi']}").json()
    assert detail["ancestors"] == [] and detail["actions"] == ["restore"]
    blocked = owner.post(f"/api/t/{tenant}/documents/{ids['pro']}/restore")
    assert blocked.json()["detail"]["code"] == "parent_retired"
    owner.post(f"/api/t/{tenant}/documents/{ids['pol']}/restore")
    assert _codes(owner, tenant) == [
        "POL-QMS-01",
        "PRO-QMS-01-01",
        "PRO-QMS-01-02",
        "WI-QMS-01-01-01",
    ]


def test_moving_within_a_system_renumbers_and_keeps_history(consultant):
    tenant, owner, qmr, ids = _setup(consultant)
    relocate = f"/api/t/{tenant}/documents/relocate"
    body = {"document_ids": [ids["wi"]], "mode": "move", "target_system": "ims"}

    # 지침은 절차 아래에만 둘 수 있다.
    wrong = owner.post(relocate, json={**body, "parent_id": ids["pol"]})
    assert wrong.json()["detail"]["code"] == "parent_type_mismatch"

    moved = owner.post(relocate, json={**body, "parent_id": ids["pro2"]}).json()
    assert [(m["old_code"], m["document"]["code"]) for m in moved["moved"]] == [
        ("WI-QMS-01-01-01", "WI-QMS-01-02-01"),
        ("TMP-QMS-01-01-01-01", "TMP-QMS-01-02-01-01"),
    ]
    detail = owner.get(f"/api/t/{tenant}/documents/{ids['wi']}").json()
    assert detail["document"]["parent_id"] == ids["pro2"]
    assert detail["approved"]["version"] == "1.0"  # 같은 문서, 같은 이력


def test_copy_and_move_to_another_system(consultant):
    tenant, owner, qmr, ids = _setup(consultant)
    new_system(consultant, tenant, slug="ims2")
    relocate = f"/api/t/{tenant}/documents/relocate"

    # 복사: 대상 체계에 새 번호의 초안으로, 하위 문서까지. 원본은 그대로다.
    copied = owner.post(
        relocate,
        json={"document_ids": [ids["pol"]], "mode": "copy", "target_system": "ims2"},
    ).json()
    assert [c["document"]["code"] for c in copied["created"]] == [
        "POL-QMS-01",
        "PRO-QMS-01-01",
        "PRO-QMS-01-02",
        "WI-QMS-01-01-01",
        "TMP-QMS-01-01-01-01",
    ]
    assert len(_codes(owner, tenant)) == 5
    tmp_copy = copied["created"][-1]["document"]["id"]
    draft = owner.get(f"/api/t/{tenant}/documents/{tmp_copy}").json()["open"]
    assert draft["status"] == "draft" and draft["version"] == "1.0"
    assert {s["body_md"] for s in draft["sections"]} == {"양식 본문"}

    # 옮기기: 대상 체계에 복사한 뒤, 원본 가운데 승인된 문서는 폐지하고 초안은 지운다.
    target = owner.get(f"/api/t/{tenant}/systems/ims2/documents").json()
    pro_copy = next(d for d in target if d["code"] == "PRO-QMS-01-02")
    moved = owner.post(
        relocate,
        json={
            "document_ids": [ids["wi"]],
            "mode": "move",
            "target_system": "ims2",
            "parent_id": pro_copy["id"],
        },
    ).json()
    assert [c["document"]["code"] for c in moved["created"]] == [
        "WI-QMS-01-02-01",
        "TMP-QMS-01-02-01-01",
    ]
    assert [d["code"] for d in moved["retired"]] == ["WI-QMS-01-01-01"]
    assert [d["code"] for d in moved["deleted"]] == ["TMP-QMS-01-01-01-01"]
    assert _codes(owner, tenant) == ["POL-QMS-01", "PRO-QMS-01-01", "PRO-QMS-01-02"]
    retired = owner.get(f"/api/t/{tenant}/documents/{ids['wi']}").json()["document"]
    assert retired["retire_reason"] == "통합경영체계(으)로 옮김"


def test_rename_and_delete_systems(consultant):
    tenant, owner, qmr, ids = _setup(consultant)
    base = consultant.get(f"/api/t/{tenant}/systems/ims").json()
    child = new_system(consultant, tenant, slug="dev", parent_id=base["id"])
    empty = new_system(consultant, tenant, slug="spare")

    # 이름 바꾸기는 회사 관리자만.
    assert owner.patch(f"/api/t/{tenant}/systems/spare", json={"name": "x"}).status_code == 403
    renamed = consultant.patch(
        f"/api/t/{tenant}/systems/spare", json={"name": "예비 체계", "description": "시험용"}
    ).json()
    assert renamed["name"] == "예비 체계" and renamed["slug"] == "spare"

    # 하위 체계와 문서가 있는 체계는 지울 수 없고, 이유를 알려준다.
    detail = consultant.get(f"/api/t/{tenant}/systems/ims").json()
    assert detail["delete_blockers"] == ["하위 체계 1개", "문서 5건"]
    blocked = consultant.delete(f"/api/t/{tenant}/systems/ims")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "system_not_empty"

    assert consultant.delete(f"/api/t/{tenant}/systems/dev").status_code == 204
    assert consultant.delete(f"/api/t/{tenant}/systems/spare").status_code == 204
    slugs = [s["slug"] for s in consultant.get(f"/api/t/{tenant}/systems").json()]
    assert slugs == ["ims"] and child["id"] and empty["id"]
    log = consultant.get(f"/api/t/{tenant}/audit-log").json()
    assert {"system.update", "system.delete"} <= {e["action"] for e in log["entries"]}


def test_deleting_a_system_keeps_its_run_history(consultant, owner_engine):
    """설계안의 작업 기록(run·run_event)은 지울 수 없으므로, 체계를 지울 때 연결만 끊는다."""
    tenant = new_tenant(consultant)
    system = new_system(consultant, tenant, slug="spare")
    with owner_engine.begin() as conn:
        tenant_id = conn.execute(
            text("SELECT id FROM tenant WHERE slug = :s"), {"s": tenant}
        ).scalar_one()
        plan_id = conn.execute(
            text(
                "INSERT INTO generation_plan "
                "(id, tenant_id, system_id, scope_code, status, structure, uncovered, results) "
                "VALUES (gen_random_uuid(), :t, :s, 'QMS', 'failed', '{}', '[]', '{}') "
                "RETURNING id"
            ),
            {"t": tenant_id, "s": system["id"]},
        ).scalar_one()
        run_id = conn.execute(
            text(
                "INSERT INTO run (id, tenant_id, kind, status, plan_id, progress, error) "
                "VALUES (gen_random_uuid(), :t, 'design_system', 'failed', :p, '{}', '') "
                "RETURNING id"
            ),
            {"t": tenant_id, "p": plan_id},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO run_event (tenant_id, run_id, level, message) "
                "VALUES (:t, :r, 'info', 'x')"
            ),
            {"t": tenant_id, "r": run_id},
        )

    assert consultant.delete(f"/api/t/{tenant}/systems/spare").status_code == 204
    with owner_engine.connect() as conn:
        plan = conn.execute(text("SELECT plan_id FROM run WHERE id = :r"), {"r": run_id}).one()
        events = conn.execute(
            text("SELECT count(*) FROM run_event WHERE run_id = :r"), {"r": run_id}
        ).scalar_one()
    assert plan.plan_id is None and events == 1
