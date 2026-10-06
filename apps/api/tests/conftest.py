"""테스트는 실제 Postgres 에서 돈다(행 수준 보안과 트리거를 검증해야 하므로).

`docker compose up -d postgres` 로 띄운 서버에 임시 DB 를 만들고, 마이그레이션과 참조 데이터를
적재한 뒤 API 는 애플리케이션 역할(pm_app)로 접속한다. 접속 정보는 환경 변수로 바꿀 수 있다.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

TEST_DB = "processminer_test"
OWNER_URL = os.environ.get(
    "PM_TEST_OWNER_URL", "postgresql+psycopg://pm_owner:pm_owner@localhost:55432/postgres"
)
APP_URL = os.environ.get(
    "PM_TEST_APP_URL", "postgresql+psycopg://pm_app:pm_app@localhost:55432/postgres"
)

_owner_test_url = make_url(OWNER_URL).set(database=TEST_DB).render_as_string(hide_password=False)
_app_test_url = make_url(APP_URL).set(database=TEST_DB).render_as_string(hide_password=False)

# 설정은 처음 읽을 때 고정되므로 app 을 import 하기 전에 지정한다.
os.environ["PM_DATABASE_URL"] = _app_test_url
os.environ["PM_MIGRATION_DATABASE_URL"] = _owner_test_url
os.environ["PM_AUTH_DEV_ECHO"] = "true"
# 작업자는 테스트가 직접 한 단계씩 돌린다(worker.process_next_run).
os.environ["PM_RUN_WORKER_IN_API"] = "false"
os.environ["PM_STORAGE_DIR"] = tempfile.mkdtemp(prefix="pm-test-storage-")
os.environ["PM_ANTHROPIC_API_KEY"] = "test-key-not-used"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppUser  # noqa: E402
from app.seed import load_reference_data  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def database():
    admin = create_engine(OWNER_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))

    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.attributes["url"] = _owner_test_url
    command.upgrade(config, "head")

    owner = create_engine(_owner_test_url)
    with Session(owner) as db:
        load_reference_data(db, get_settings().seed_dir)
        db.commit()
    owner.dispose()

    yield

    get_engine().dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture
def owner_engine():
    """소유자(슈퍼유저) 접속. 행 수준 보안을 우회하므로 검증용 조회·준비에만 쓴다."""
    engine = create_engine(_owner_test_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine():
    return get_engine()


def make_user(name: str, platform_role: str | None = None) -> str:
    """사용자를 만들고 이메일을 돌려준다."""
    email = f"{uuid.uuid4().hex[:10]}@test.example"
    with Session(get_engine()) as db:
        db.add(AppUser(email=email, name=name, platform_role=platform_role))
        db.commit()
    return email


def login(email: str) -> TestClient:
    """이메일 링크 흐름으로 로그인한 클라이언트."""
    client = TestClient(app)
    link = client.post("/api/auth/request-link", json={"email": email}).json()["dev_link"]
    assert link, "등록된 사용자여야 로그인 링크가 나온다"
    token = link.split("token=")[1]
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 200
    return client


@pytest.fixture
def consultant() -> TestClient:
    return login(make_user("컨설턴트", "consultant"))


def new_tenant(client: TestClient, name: str = "테스트 회사") -> str:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    response = client.post("/api/tenants", json={"slug": slug, "name": name})
    assert response.status_code == 201, response.text
    return slug


def new_system(client: TestClient, tenant: str, slug: str = "ims", parent_id=None) -> dict:
    root = client.get(f"/api/t/{tenant}/org-units").json()[0]
    response = client.post(
        f"/api/t/{tenant}/systems",
        json={
            "slug": slug,
            "name": "통합경영체계",
            "org_unit_id": root["id"],
            "parent_system_id": parent_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_member(client: TestClient, tenant: str, name: str, roles: list[str]) -> TestClient:
    """회사에 구성원을 추가하고 그 사람으로 로그인한 클라이언트를 돌려준다."""
    email = f"{uuid.uuid4().hex[:10]}@test.example"
    response = client.post(
        f"/api/t/{tenant}/members",
        json={"email": email, "name": name, "roles": [{"role": r} for r in roles]},
    )
    assert response.status_code == 201, response.text
    return login(email)
