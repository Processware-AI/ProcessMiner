"""감사 기록. 회사별로 해시를 이어 붙인 추가 전용 기록이다."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog

GENESIS_HASH = "0" * 64


def _digest(
    prev_hash: str,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    data: dict[str, Any],
    at: datetime,
) -> str:
    payload = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "actor_id": str(actor_id) if actor_id else None,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "data": data,
            "at": at.astimezone(UTC).isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str,
    data: dict[str, Any] | None = None,
) -> AuditLog:
    data = data or {}
    entity_id = str(entity_id)
    # 같은 회사의 기록이 동시에 들어와도 사슬이 갈라지지 않게 트랜잭션 동안 직렬화한다.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"audit:{tenant_id}"})
    prev_hash = (
        db.scalar(
            select(AuditLog.hash)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        or GENESIS_HASH
    )
    at = datetime.now(UTC)
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data,
        at=at,
        prev_hash=prev_hash,
        hash=_digest(prev_hash, tenant_id, actor_id, action, entity_type, entity_id, data, at),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session, tenant_id: uuid.UUID) -> int | None:
    """사슬을 처음부터 다시 계산한다. 어긋난 첫 행의 id 를 돌려주고, 온전하면 None."""
    prev_hash = GENESIS_HASH
    rows = db.scalars(select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.id))
    for row in rows:
        expected = _digest(
            prev_hash,
            row.tenant_id,
            row.actor_id,
            row.action,
            row.entity_type,
            row.entity_id,
            row.data,
            row.at,
        )
        if row.prev_hash != prev_hash or row.hash != expected:
            return row.id
        prev_hash = row.hash
    return None
