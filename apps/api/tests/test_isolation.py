"""회사 간 격리. API 계층이 아니라 DB 가 막는지를 본다."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.conftest import login, make_user, new_system, new_tenant


def _tenant_id(engine, slug):
    with engine.connect() as conn:
        return conn.execute(text("SELECT id FROM tenant WHERE slug = :s"), {"s": slug}).scalar_one()


def _make_policy(client, tenant):
    new_system(client, tenant)
    response = client.post(
        f"/api/t/{tenant}/systems/ims/documents",
        json={"doc_type": "POL", "title": "격리 확인 정책", "scope_code": "QMS"},
    )
    assert response.status_code == 201, response.text
    return response.json()["document"]["id"]


def test_rows_are_invisible_without_or_with_another_tenant_context(consultant, app_engine):
    tenant_a, tenant_b = new_tenant(consultant), new_tenant(consultant)
    _make_policy(consultant, tenant_a)
    _make_policy(consultant, tenant_b)
    id_a, id_b = _tenant_id(app_engine, tenant_a), _tenant_id(app_engine, tenant_b)

    with app_engine.begin() as conn:
        # 회사가 지정되지 않으면 아무 행도 보이지 않는다.
        assert conn.execute(text("SELECT count(*) FROM document")).scalar_one() == 0

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(id_a)})
        seen = conn.execute(text("SELECT DISTINCT tenant_id FROM document")).scalars().all()
        assert seen == [id_a]
        assert (
            conn.execute(
                text("SELECT count(*) FROM document WHERE tenant_id = :t"), {"t": id_b}
            ).scalar_one()
            == 0
        )


def test_cannot_write_rows_for_another_tenant(consultant, app_engine):
    tenant_a, tenant_b = new_tenant(consultant), new_tenant(consultant)
    id_a, id_b = _tenant_id(app_engine, tenant_a), _tenant_id(app_engine, tenant_b)

    with pytest.raises(ProgrammingError, match="row-level security"), app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(id_a)})
        conn.execute(
            text(
                "INSERT INTO org_unit (id, tenant_id, kind, name, sort) "
                "VALUES (gen_random_uuid(), :t, 'team', '침입', 0)"
            ),
            {"t": id_b},
        )


def test_api_hides_other_tenants(consultant):
    tenant = new_tenant(consultant)
    document_id = _make_policy(consultant, tenant)

    outsider = login(make_user("다른 회사 컨설턴트", "consultant"))
    other_tenant = new_tenant(outsider)
    new_system(outsider, other_tenant)

    # 소속되지 않은 회사는 존재 여부도 알 수 없다.
    assert outsider.get(f"/api/t/{tenant}").status_code == 404
    assert outsider.get(f"/api/t/{tenant}/documents/{document_id}").status_code == 404
    # 자기 회사 경로로 남의 문서 id 를 넣어도 찾지 못한다.
    assert outsider.get(f"/api/t/{other_tenant}/documents/{document_id}").status_code == 404


def test_audit_log_is_append_only_for_the_app_role(consultant, app_engine):
    tenant = new_tenant(consultant)
    tenant_id = _tenant_id(app_engine, tenant)

    for statement in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"):
        with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            conn.execute(text(statement))


def test_reference_data_is_read_only_for_the_app_role(app_engine):
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("UPDATE doc_type_def SET name = '변조'"))


def test_approved_revision_cannot_be_changed_even_by_the_owner(consultant, owner_engine):
    tenant = new_tenant(consultant)
    document_id = _make_policy(consultant, tenant)
    consultant.patch(f"/api/t/{tenant}", json={"four_eyes": False})
    detail = consultant.get(f"/api/t/{tenant}/documents/{document_id}").json()
    revision_id = detail["open"]["id"]
    sections = [{**s, "body_md": "내용"} for s in detail["open"]["sections"]]
    assert (
        consultant.patch(
            f"/api/t/{tenant}/revisions/{revision_id}", json={"sections": sections}
        ).status_code
        == 200
    )
    assert consultant.post(f"/api/t/{tenant}/revisions/{revision_id}/submit").status_code == 200
    assert (
        consultant.post(f"/api/t/{tenant}/revisions/{revision_id}/approve", json={}).status_code
        == 200
    )

    for statement in (
        "UPDATE document_revision SET title = '변조' WHERE id = :id",
        "UPDATE document_revision SET status = 'draft' WHERE id = :id",
        "DELETE FROM document_revision WHERE id = :id",
    ):
        with pytest.raises(DBAPIError), owner_engine.begin() as conn:
            conn.execute(text(statement), {"id": revision_id})
