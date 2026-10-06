"""응답을 받은 직후의 조회는 방금 바꾼 내용을 봐야 한다.

커밋이 응답을 보낸 뒤에 일어나면 화면이 곧바로 다시 조회할 때 이전 상태가 보인다.
TestClient 로는 이 순서가 드러나지 않으므로 실제 서버를 띄워 확인한다.
"""

import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from app.main import app
from tests.conftest import make_user


@pytest.fixture
def live_server():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "서버가 시작되지 않았습니다"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_changes_are_visible_as_soon_as_the_response_arrives(live_server):
    client = httpx.Client(base_url=live_server)
    email = make_user("컨설턴트", "consultant")
    link = client.post("/api/auth/request-link", json={"email": email}).json()["dev_link"]
    assert client.post("/api/auth/verify", json={"token": link.split("token=")[1]}).is_success

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    assert client.post("/api/tenants", json={"slug": tenant, "name": "회사"}).is_success
    root = client.get(f"/api/t/{tenant}/org-units").json()[0]["id"]
    system = {"slug": "ims", "name": "체계", "org_unit_id": root}
    assert client.post(f"/api/t/{tenant}/systems", json=system).is_success
    assert client.patch(f"/api/t/{tenant}", json={"four_eyes": False}).is_success

    for i in range(30):
        created = client.post(
            f"/api/t/{tenant}/systems/ims/documents",
            json={"doc_type": "POL", "title": f"정책 {i}", "scope_code": "QMS"},
        ).json()
        document_id, revision = created["document"]["id"], created["open"]
        listed = client.get(f"/api/t/{tenant}/systems/ims/documents").json()
        assert document_id in {d["id"] for d in listed}

        sections = [{**s, "body_md": "내용"} for s in revision["sections"]]
        base = f"/api/t/{tenant}/revisions/{revision['id']}"
        assert client.patch(base, json={"sections": sections}).is_success
        assert client.post(f"{base}/submit").json()["status"] == "in_review"
        # 직전 요청의 커밋이 늦으면 여기서 '초안 상태에서는 할 수 없다' 로 실패한다.
        approved = client.post(f"{base}/approve", json={})
        assert approved.status_code == 200, approved.text
        detail = client.get(f"/api/t/{tenant}/documents/{document_id}").json()
        assert detail["approved"] is not None and detail["open"] is None
