"""원문 파일 보관. 지금은 서버의 디렉터리에 두고, 운영에서는 객체 저장소로 바꾼다.

회사마다 디렉터리를 나눈다. 파일 이름은 내용의 지문이라 같은 파일을 두 번 올려도 하나만 남는다.
"""

import shutil
import uuid
from pathlib import Path

from app.config import get_settings


def _tenant_dir(tenant_id: uuid.UUID) -> Path:
    return get_settings().storage_dir / str(tenant_id)


def save(tenant_id: uuid.UUID, sha256: str, suffix: str, data: bytes) -> str:
    """파일을 저장하고 보관 위치(키)를 돌려준다."""
    directory = _tenant_dir(tenant_id)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{sha256}{suffix}"
    (directory / name).write_bytes(data)
    return f"{tenant_id}/{name}"


def load(key: str) -> bytes:
    return (get_settings().storage_dir / key).read_bytes()


def delete(key: str) -> None:
    (get_settings().storage_dir / key).unlink(missing_ok=True)


def delete_tenant(tenant_id: uuid.UUID) -> None:
    """회사를 완전히 삭제할 때 그 회사의 파일을 모두 지운다."""
    shutil.rmtree(_tenant_dir(tenant_id), ignore_errors=True)
