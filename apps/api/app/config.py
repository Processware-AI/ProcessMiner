from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env", extra="ignore")

    # API 는 슈퍼유저가 아닌 역할로 접속해야 RLS 가 적용된다.
    database_url: str = "postgresql+psycopg://pm_app:pm_app@localhost:55432/processminer"
    # 마이그레이션·참조 데이터 적재는 소유자 역할로 수행한다.
    migration_database_url: str = (
        "postgresql+psycopg://pm_owner:pm_owner@localhost:55432/processminer"
    )

    web_base_url: str = "http://localhost:3000"
    session_cookie: str = "pm_session"
    session_days: int = 14
    login_token_minutes: int = 15
    cookie_secure: bool = False
    # 개발용: 로그인 링크를 메일로 보내는 대신 응답과 로그에 그대로 노출한다.
    auth_dev_echo: bool = False

    seed_dir: Path = REPO_ROOT / "seed"

    # 업로드한 원문 파일을 두는 곳. 운영에서는 객체 저장소로 바꾼다.
    storage_dir: Path = REPO_ROOT / "var" / "storage"
    max_upload_mb: int = 50

    # 요건 도출·문서 생성에 쓰는 모델.
    # 키가 없으면 SDK 의 기본 인증(환경 변수, 로그인 프로필)을 쓴다.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    # 한 번에 보내는 요청 수. 조직의 호출 한도에 맞춘다.
    llm_concurrency: int = 4

    # API 프로세스 안에서 작업자를 함께 돌린다. 따로 띄울 때(python -m app.worker)는 끈다.
    run_worker_in_api: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
