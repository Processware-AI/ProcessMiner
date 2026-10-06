"""이메일 링크 로그인과 세션.

가입은 없다. 미리 등록(초대)된 사용자만 로그인할 수 있다.
다른 로그인 방식(OIDC 등)을 붙일 때는 사용자를 찾은 뒤 create_session 을 호출하면 된다.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppUser, AuthSession, LoginToken

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_login_link(db: Session, email: str) -> str | None:
    """로그인 링크를 만든다. 등록되지 않았거나 비활성 사용자면 None."""
    settings = get_settings()
    user = db.scalar(select(AppUser).where(AppUser.email == normalize_email(email)))
    if user is None or not user.is_active:
        return None

    token = secrets.token_urlsafe(32)
    db.add(
        LoginToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.login_token_minutes),
        )
    )
    db.flush()
    link = f"{settings.web_base_url}/auth/verify?token={token}"
    if settings.auth_dev_echo:
        logger.warning("로그인 링크(개발용) %s → %s", user.email, link)
    return link


def consume_login_token(db: Session, token: str) -> AppUser | None:
    """토큰을 한 번만 쓸 수 있게 소비하고 사용자를 돌려준다."""
    row = db.scalar(
        select(LoginToken).where(LoginToken.token_hash == hash_token(token)).with_for_update()
    )
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at < now:
        return None
    user = db.get(AppUser, row.user_id)
    if user is None or not user.is_active:
        return None
    row.used_at = now
    return user


def create_session(db: Session, user_id: uuid.UUID) -> str:
    """세션을 만들고 쿠키에 넣을 토큰 원문을 돌려준다."""
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().session_days),
        )
    )
    db.flush()
    return token


def user_for_session(db: Session, token: str) -> AppUser | None:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.expires_at < datetime.now(UTC):
        return None
    user = db.get(AppUser, session.user_id)
    if user is None or not user.is_active:
        return None
    return user


def delete_session(db: Session, token: str) -> None:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is not None:
        db.delete(session)
