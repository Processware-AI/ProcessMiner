"""DB 세션과 회사(tenant) 컨텍스트.

행 수준 보안 정책은 트랜잭션 변수 app.tenant_id 를 본다. 세션에 회사를 지정해 두면
트랜잭션이 시작될 때마다 그 값을 다시 설정한다(커밋 후 새 트랜잭션 포함).
"""

import uuid
from collections.abc import Awaitable, Callable, Iterator
from functools import lru_cache

from fastapi import Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_TENANT_KEY = "tenant_id"


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def _apply_tenant(connection, tenant_id: str) -> None:
    connection.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@event.listens_for(Session, "after_begin")
def _set_tenant_on_begin(session: Session, transaction, connection) -> None:
    tenant_id = session.info.get(_TENANT_KEY)
    if tenant_id:
        _apply_tenant(connection, tenant_id)


def set_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    """이 세션의 이후 모든 쿼리를 해당 회사 범위로 묶는다."""
    session.info[_TENANT_KEY] = str(tenant_id)
    # 이미 트랜잭션이 열려 있으면 after_begin 이 다시 호출되지 않으므로 직접 적용한다.
    _apply_tenant(session.connection(), str(tenant_id))


def get_db(request: Request) -> Iterator[Session]:
    """요청마다 세션 하나. 커밋은 CommitRoute 가 응답을 만들기 전에 한다.

    여기서(yield 뒤에) 커밋하면 응답을 보낸 뒤에 실행되어, 화면이 응답을 받자마자 다시
    조회할 때 방금 바꾼 내용이 보이지 않는 경우가 생긴다. 처리 중 오류가 나면 커밋 없이
    닫히므로 변경은 버려진다.
    """
    session = get_sessionmaker()()
    request.state.db = session
    try:
        yield session
    finally:
        session.close()


class CommitRoute(APIRoute):
    """요청 처리 함수가 정상적으로 끝나면 응답을 돌려주기 전에 커밋한다.

    커밋이 실패하면(제약 위반 등) 성공 응답 대신 오류가 나간다.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def commit_then_respond(request: Request) -> Response:
            response = await handler(request)
            session: Session | None = getattr(request.state, "db", None)
            if session is not None:
                await run_in_threadpool(session.commit)
            return response

        return commit_then_respond
