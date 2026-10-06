"""문서 번호 발급.

파일을 훑어 최댓값+1 을 쓰던 방식(tools/vault_rules/scanner.py)은 동시 실행에서 충돌하므로,
DB 카운터를 한 문장으로 증가시켜 발급한다. 번호는 상속 계보(root_system_id) 안에서 유일하다.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.doc_ids import new_child_id, new_root_id
from app.domain.doc_types import PARENT_TYPE, SCOPED_ROOT_TYPES


def _next_seq(db: Session, tenant_id: uuid.UUID, root_system_id: uuid.UUID, key: str) -> int:
    return db.execute(
        text(
            """
            INSERT INTO doc_sequence (root_system_id, key, tenant_id, last)
            VALUES (:root, :key, :tenant, 1)
            ON CONFLICT (root_system_id, key)
            DO UPDATE SET last = doc_sequence.last + 1
            RETURNING last
            """
        ),
        {"root": root_system_id, "key": key, "tenant": tenant_id},
    ).scalar_one()


def allocate_code(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    root_system_id: uuid.UUID,
    doc_type: str,
    scope_code: str | None,
    parent_code: str | None,
) -> str:
    """다음 문서 번호를 발급한다. 형식이 맞지 않으면 ValueError."""
    if doc_type in PARENT_TYPE:
        if parent_code is None:
            raise ValueError(f"{doc_type} requires a parent document")
        seq = _next_seq(db, tenant_id, root_system_id, f"{doc_type}:{parent_code}")
        return new_child_id(parent_code, doc_type, seq)

    if doc_type in SCOPED_ROOT_TYPES:
        if not scope_code:
            raise ValueError(f"{doc_type} requires a scope code")
        seq = _next_seq(db, tenant_id, root_system_id, f"{doc_type}:{scope_code}")
        return new_root_id(doc_type, scope_code, seq)

    seq = _next_seq(db, tenant_id, root_system_id, doc_type)
    return new_root_id(doc_type, "", seq)
