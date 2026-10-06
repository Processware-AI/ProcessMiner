"""회사 보관과 완전 삭제.

보관: 데이터는 남기고 읽기 전용으로 만든다. 회사 관리자가 하고 되돌릴 수 있다.
완전 삭제: 보관된 회사에 한해 플랫폼 관리자가 회사 주소를 입력해 확인한 뒤에만 한다.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import add_member, login, make_user, new_system, new_tenant


def _approved_policy(author, reviewer, tenant, title="정책"):
    detail = author.post(
        f"/api/t/{tenant}/systems/ims/documents",
        json={"doc_type": "POL", "title": title, "scope_code": "QMS"},
    ).json()
    revision = f"/api/t/{tenant}/revisions/{detail['open']['id']}"
    sections = [{**s, "body_md": "내용"} for s in detail["open"]["sections"]]
    assert author.patch(revision, json={"sections": sections}).status_code == 200
    assert author.post(f"{revision}/submit").status_code == 200
    assert reviewer.post(f"{revision}/approve", json={}).status_code == 200
    return detail["document"]["id"]


def _company(consultant):
    tenant = new_tenant(consultant)
    new_system(consultant, tenant)
    owner = add_member(consultant, tenant, "프로세스 오너", ["process_owner"])
    qmr = add_member(consultant, tenant, "품질 책임자", ["qmr"])
    document_id = _approved_policy(owner, qmr, tenant)
    return tenant, owner, qmr, document_id


def _slugs(client):
    return {t["slug"]: t for t in client.get("/api/me").json()["tenants"]}


def test_archived_company_is_read_only_and_hidden_from_members(consultant):
    tenant, owner, _, document_id = _company(consultant)

    # 구성원은 보관할 수 없다.
    assert owner.post(f"/api/t/{tenant}/archive").status_code == 403

    archived = consultant.post(f"/api/t/{tenant}/archive").json()
    assert archived["archived_at"] is not None
    # 보관된 회사에서 할 수 있는 일은 읽기와 복원뿐이다.
    assert "tenant.restore" in archived["actions"]
    assert not {"tenant.manage", "tenant.archive", "doc.create", "member.manage"} & set(
        archived["actions"]
    )

    # 관리자는 계속 읽을 수 있다.
    detail = consultant.get(f"/api/t/{tenant}/documents/{document_id}")
    assert detail.status_code == 200 and detail.json()["actions"] == []
    assert _slugs(consultant)[tenant]["archived_at"] is not None

    # 바꾸는 요청은 종류와 상관없이 막힌다.
    for method, path, body in [
        ("post", f"/api/t/{tenant}/systems/ims/documents", {"doc_type": "REF", "title": "x"}),
        ("post", f"/api/t/{tenant}/documents/{document_id}/revisions", {}),
        ("patch", f"/api/t/{tenant}", {"name": "새 이름"}),
        ("post", f"/api/t/{tenant}/archive", None),
    ]:
        response = getattr(consultant, method)(path, json=body)
        assert response.status_code == 409, (path, response.text)
        assert response.json()["detail"]["code"] == "tenant_archived"

    # 일반 구성원에게는 회사가 없는 것처럼 보인다.
    assert owner.get(f"/api/t/{tenant}").status_code == 404
    assert tenant not in _slugs(owner)


def test_restore_brings_everything_back(consultant):
    tenant, owner, _, document_id = _company(consultant)
    assert consultant.post(f"/api/t/{tenant}/archive").status_code == 200

    # 보관되지 않은 상태에서는 복원할 것이 없고, 구성원은 복원할 수 없다(회사가 보이지 않는다).
    assert owner.post(f"/api/t/{tenant}/restore").status_code == 404

    restored = consultant.post(f"/api/t/{tenant}/restore").json()
    assert restored["archived_at"] is None and "tenant.restore" not in restored["actions"]
    assert consultant.post(f"/api/t/{tenant}/restore").status_code == 403

    assert owner.get(f"/api/t/{tenant}/documents/{document_id}").status_code == 200
    assert (
        owner.post(f"/api/t/{tenant}/documents/{document_id}/revisions", json={}).status_code == 201
    )

    log = consultant.get(f"/api/t/{tenant}/audit-log").json()
    actions = [e["action"] for e in log["entries"]]
    assert actions[:3] == ["revision.start", "tenant.restore", "tenant.archive"]


def test_purge_requires_archive_platform_admin_and_confirmation(consultant):
    tenant, _, _, _ = _company(consultant)
    admin = login(make_user("플랫폼 관리자", "platform_admin"))
    purge = f"/api/t/{tenant}/purge"

    # 보관하지 않은 회사는 플랫폼 관리자도 지울 수 없다.
    response = admin.post(purge, json={"confirm_slug": tenant})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "not_archived"

    assert consultant.post(f"/api/t/{tenant}/archive").status_code == 200
    # 회사 관리자는 지울 수 없다.
    assert consultant.post(purge, json={"confirm_slug": tenant}).status_code == 403
    # 회사 주소를 정확히 입력해야 한다.
    response = admin.post(purge, json={"confirm_slug": "wrong"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "confirm_mismatch"
    assert admin.get(f"/api/t/{tenant}").status_code == 200  # 아직 남아 있다


def test_purge_removes_all_company_data_and_leaves_a_tombstone(consultant, owner_engine):
    tenant, owner, _, _ = _company(consultant)
    keep, _, _, keep_document = _company(consultant)  # 다른 회사는 영향받지 않아야 한다
    admin = login(make_user("플랫폼 관리자", "platform_admin"))

    with owner_engine.connect() as conn:
        tenant_id = conn.execute(
            text("SELECT id FROM tenant WHERE slug = :s"), {"s": tenant}
        ).scalar_one()
        owner_email = conn.execute(
            text(
                "SELECT u.email FROM app_user u JOIN membership m ON m.user_id = u.id "
                "WHERE m.tenant_id = :t AND u.name = '프로세스 오너'"
            ),
            {"t": tenant_id},
        ).scalar_one()

    assert consultant.post(f"/api/t/{tenant}/archive").status_code == 200
    response = admin.post(f"/api/t/{tenant}/purge", json={"confirm_slug": tenant})
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["documents"] == 1 and summary["revisions"] == 1 and summary["members"] == 3
    # 이 회사에만 속했던 두 사람의 계정은 함께 지워지고, 다른 회사에도 속한 컨설턴트는 남는다.
    assert summary["accounts_removed"] == 2

    assert admin.get(f"/api/t/{tenant}").status_code == 404
    assert tenant not in _slugs(consultant)
    assert consultant.get("/api/me").status_code == 200
    # 지워진 계정의 세션은 더 이상 통하지 않는다.
    assert owner.get("/api/me").status_code == 401

    with owner_engine.connect() as conn:
        for table in (
            "audit_log",
            "document",
            "document_revision",
            "process_system",
            "org_unit",
            "role_assignment",
            "doc_sequence",
            "membership",
        ):
            remaining = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
            ).scalar_one()
            assert remaining == 0, table
        assert (
            conn.execute(
                text("SELECT count(*) FROM app_user WHERE email = :e"), {"e": owner_email}
            ).scalar_one()
            == 0
        )
        tombstone = conn.execute(
            text("SELECT slug, deleted_by_email, summary FROM deleted_tenant WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).one()
        assert tombstone.slug == tenant and tombstone.summary["last_audit_hash"]

    # 다른 회사는 그대로이고, 감사 기록의 사슬도 온전하다.
    assert consultant.get(f"/api/t/{keep}/documents/{keep_document}").status_code == 200
    assert consultant.get(f"/api/t/{keep}/audit-log").json()["chain_intact"] is True

    # 지운 주소는 다시 쓸 수 있다.
    assert consultant.post("/api/tenants", json={"slug": tenant, "name": "다시"}).status_code == 201


def test_purge_function_cannot_be_used_to_bypass_the_safeguards(consultant, app_engine):
    tenant, _, _, _ = _company(consultant)
    with app_engine.connect() as conn:
        tenant_id, user_id = conn.execute(
            text(
                "SELECT t.id, m.user_id FROM tenant t JOIN membership m ON m.tenant_id = t.id "
                "WHERE t.slug = :s LIMIT 1"
            ),
            {"s": tenant},
        ).one()

    # 보관하지 않은 회사는 함수를 직접 불러도 지워지지 않는다.
    with pytest.raises(DBAPIError, match="must be archived"), app_engine.begin() as conn:
        conn.execute(text("SELECT purge_tenant(:t, :u)"), {"t": tenant_id, "u": user_id})

    # 삭제 중이라는 표시를 흉내 내도, 애플리케이션 역할로는 승인판을 지울 수 없다.
    with pytest.raises(DBAPIError, match="only draft revisions"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            text("SELECT set_config('app.purging_tenant', :t, true)"), {"t": str(tenant_id)}
        )
        conn.execute(text("DELETE FROM document_revision"))

    # 감사 기록과 삭제 흔적은 여전히 애플리케이션 역할이 건드릴 수 없다.
    for statement in ("DELETE FROM audit_log", "DELETE FROM deleted_tenant"):
        with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
            conn.execute(text(statement))
