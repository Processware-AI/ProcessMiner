"""운영·개발용 명령.

python -m app.cli migrate                     # 스키마를 최신으로
python -m app.cli seed                        # 참조 데이터 적재
python -m app.cli create-user EMAIL NAME [--platform-role platform_admin|consultant]
python -m app.cli login-link EMAIL            # 로그인 링크 출력(메일 없이 로그인)
python -m app.cli demo                        # 데모 회사와 예시 문서 생성
python -m app.cli purge-tenant SLUG --actor EMAIL --yes   # 회사 완전 삭제(되돌릴 수 없음)
python -m app.cli openapi --out FILE          # OpenAPI 스키마(JSON) 저장
"""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.db import get_sessionmaker, set_tenant
from app.domain.permissions import TENANT_ADMIN, TENANT_MEMBER
from app.models import AppUser, Membership, OrgUnit, ProcessSystem, RoleAssignment, Tenant
from app.schemas import DocumentIn, RevisionPatch, Section
from app.services import auth as auth_service
from app.services import documents as doc_service

API_DIR = Path(__file__).resolve().parents[1]


def cmd_migrate(_: argparse.Namespace) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(config, "head")
    print("스키마가 최신입니다.")


def cmd_seed(_: argparse.Namespace) -> None:
    from app.seed import load_reference_data

    settings = get_settings()
    engine = create_engine(settings.migration_database_url)
    with Session(engine) as db:
        counts = load_reference_data(db, settings.seed_dir)
        db.commit()
    print(f"참조 데이터 적재 완료: {counts}")


def _get_or_create_user(
    db: Session, email: str, name: str, platform_role: str | None = None
) -> AppUser:
    email = auth_service.normalize_email(email)
    user = db.scalar(select(AppUser).where(AppUser.email == email))
    if user is None:
        user = AppUser(email=email, name=name, platform_role=platform_role)
        db.add(user)
        db.flush()
    return user


def cmd_create_user(args: argparse.Namespace) -> None:
    with get_sessionmaker()() as db:
        user = _get_or_create_user(db, args.email, args.name, args.platform_role)
        if args.platform_role and user.platform_role != args.platform_role:
            user.platform_role = args.platform_role
        db.commit()
        print(f"사용자 준비됨: {user.email} (플랫폼 역할: {user.platform_role or '없음'})")


def cmd_login_link(args: argparse.Namespace) -> None:
    with get_sessionmaker()() as db:
        link = auth_service.create_login_link(db, args.email)
        db.commit()
    if link is None:
        sys.exit(f"등록되지 않은 사용자입니다: {args.email}")
    print(link)


def cmd_openapi(args: argparse.Namespace) -> None:
    from app.main import app

    # 콘솔 인코딩에 좌우되지 않도록 파일에 UTF-8 로 직접 쓴다.
    Path(args.out).write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OpenAPI 스키마 저장: {args.out}")


def cmd_purge_tenant(args: argparse.Namespace) -> None:
    """회사를 보관하고 완전히 지운다. 테스트로 만든 회사를 정리할 때 쓴다."""
    with get_sessionmaker()() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.slug))
        actor = db.scalar(
            select(AppUser).where(AppUser.email == auth_service.normalize_email(args.actor))
        )
        if tenant is None:
            sys.exit(f"회사를 찾을 수 없습니다: {args.slug}")
        if actor is None:
            sys.exit(f"사용자를 찾을 수 없습니다: {args.actor}")
        if not args.yes:
            sys.exit("되돌릴 수 없는 작업입니다. 실행하려면 --yes 를 붙이세요.")
        if tenant.archived_at is None:
            tenant.archived_at = datetime.now(UTC)
            tenant.archived_by = actor.id
            db.flush()
        summary = db.execute(
            text("SELECT purge_tenant(:tenant, :actor)"), {"tenant": tenant.id, "actor": actor.id}
        ).scalar_one()
        tenant_id = tenant.id
        db.expunge_all()
        db.commit()
    storage.delete_tenant(tenant_id)
    print(f"삭제 완료: {args.slug} {summary}")


# ── 데모 데이터 ──────────────────────────────────────────────────────────────

DEMO_SLUG = "demo"

_DEMO_DOCS = {
    "POL": {
        "title": "문서화된 정보 관리 정책",
        "sections": {
            "purpose": "조직의 정책·절차·지침·기록이 최신 상태로 유지되고, 필요한 사람이 필요한 때에 "
            "올바른 판을 쓸 수 있도록 관리 원칙을 정한다.",
            "scope": "전사의 모든 프로세스 문서(정책서, 절차서, 업무지침서, 템플릿)와 그에 따라 "
            "생성되는 기록에 적용한다.",
            "principles": "1. 모든 문서는 고유 번호와 버전을 가진다.\n"
            "2. 승인되지 않은 문서는 업무 기준으로 쓰지 않는다.\n"
            "3. 승인된 판은 수정하지 않는다. 바꿀 때는 새 개정판을 만든다.\n"
            "4. 작성자와 승인자는 서로 다른 사람이어야 한다.",
            "roles": "| 역할 | 책임 |\n|---|---|\n"
            "| 프로세스 오너 | 담당 문서의 작성·개정, 정기 검토 |\n"
            "| 품질 책임자 | 문서 검토·승인, 문서 체계의 일관성 유지 |\n"
            "| 구성원 | 승인된 최신판에 따른 업무 수행 |",
            "compliance": "연 1회 이상 모든 문서의 유효성을 검토한다. 예외는 품질 책임자의 승인을 받는다.",
        },
    },
    "PRO": {
        "title": "문서 개정 관리 절차",
        "sections": {
            "purpose": "문서를 개정할 때 따르는 요청·작성·검토·승인·배포의 흐름을 정한다.",
            "scope": "문서화된 정보 관리 정책의 적용을 받는 모든 문서의 제정과 개정.",
            "raci": "| 단계 | R | A | C | I |\n|---|---|---|---|---|\n"
            "| 개정 요청 | 요청자 | 프로세스 오너 | - | 품질 책임자 |\n"
            "| 초안 작성 | 프로세스 오너 | 프로세스 오너 | 관련 부서 | - |\n"
            "| 검토·승인 | 품질 책임자 | 품질 책임자 | 프로세스 오너 | 구성원 |",
            "flow": "```mermaid\nflowchart TD\n  A[개정 요청] --> B[초안 작성] --> C{검토}\n"
            "  C -- 반려 --> B\n  C -- 승인 --> D[배포·공지]\n```\n\n"
            "| # | 단계 | 설명 | 담당 | 입력 | 출력 |\n|---|---|---|---|---|---|\n"
            "| 1 | 개정 요청 | 개정 사유와 범위를 적어 요청한다 | 요청자 | 개선 의견, 부적합 | 개정 요청서 |\n"
            "| 2 | 초안 작성 | 현행 승인판에서 초안을 만든다 | 프로세스 오너 | 개정 요청서 | 초안 |\n"
            "| 3 | 검토·승인 | 내용과 영향 범위를 검토한다 | 품질 책임자 | 초안 | 승인판 |\n"
            "| 4 | 배포·공지 | 승인판을 게시하고 변경점을 알린다 | 프로세스 오너 | 승인판 | 공지 |",
            "controls": "| 통제점 | 지표 | 목표 | 주기 |\n|---|---|---|---|\n"
            "| 검토 소요 | 제출부터 승인까지 영업일 | 5일 이내 | 월 |\n"
            "| 정기 검토 | 1년 내 검토된 문서 비율 | 100% | 연 |",
        },
    },
    "WI": {
        "title": "개정 및 버전 관리 지침",
        "sections": {
            "purpose": "개정판을 만들고 버전을 올리는 구체적인 방법을 정한다.",
            "performer": "수행: 프로세스 오너 · 검토·승인: 품질 책임자",
            "scope": "",
            "io": "- **입력**: 개정 요청서, 현행 승인판\n- **산출물**: 승인된 개정판, 개정 이력",
            "prep": "현행 승인판과 개정 요청 내용을 확인한다.",
            "steps": "1. 개정 구분을 정한다. 오탈자·표현 수정은 경미 개정, 구조·책임·범위 변경은 주요 개정이다.\n"
            "2. 현행 승인판에서 새 초안을 만든다. 버전은 경미 개정이면 x.y+1, 주요 개정이면 x+1.0 이 된다.\n"
            "3. 변경 요약에 무엇을 왜 바꿨는지 적는다.\n"
            "4. 검토를 요청한다.\n"
            "5. 반려되면 사유를 반영해 다시 제출한다.",
            "done": "개정판이 승인되고 이전 판이 대체됨으로 표시된다.",
            "interfaces": "",
            "exceptions": "긴급 개정도 승인 없이 배포하지 않는다.",
        },
    },
    "TMP": {
        "title": "문서 개정 요청서",
        "sections": {
            "guide": "개정을 요청하는 사람이 작성한다. 결재: 요청자 → 프로세스 오너.",
            "fields": "| 항목 | 내용 |\n|---|---|\n| 대상 문서 번호 |  |\n| 요청자 |  |\n| 요청일 |  |\n"
            "| 개정 사유 |  |\n| 개정 범위 |  |\n| 개정 구분 (경미/주요) |  |\n| 승인 |  |",
        },
    },
}


def _fill(db: Session, document_id, content: dict) -> None:
    revision = doc_service.open_revision(db, document_id)
    doc_service.update_revision(
        db,
        revision=revision,
        patch=RevisionPatch(
            sections=[Section(key=k, title="", body_md=v) for k, v in content["sections"].items()]
        ),
    )


def cmd_demo(_: argparse.Namespace) -> None:
    with get_sessionmaker()() as db:
        if db.scalar(select(Tenant.id).where(Tenant.slug == DEMO_SLUG)) is not None:
            print("데모 회사가 이미 있습니다. 건너뜁니다.")
            return

        admin = _get_or_create_user(db, "admin@example.com", "플랫폼 관리자", "platform_admin")
        owner = _get_or_create_user(db, "owner@example.com", "프로세스 오너")
        qmr = _get_or_create_user(db, "qmr@example.com", "품질 책임자")
        viewer = _get_or_create_user(db, "member@example.com", "일반 구성원")

        tenant = Tenant(slug=DEMO_SLUG, name="데모 주식회사", settings={"four_eyes": True})
        db.add(tenant)
        db.flush()
        db.add_all(
            [
                Membership(user_id=admin.id, tenant_id=tenant.id, tenant_role=TENANT_ADMIN),
                Membership(user_id=owner.id, tenant_id=tenant.id, tenant_role=TENANT_MEMBER),
                Membership(user_id=qmr.id, tenant_id=tenant.id, tenant_role=TENANT_MEMBER),
                Membership(user_id=viewer.id, tenant_id=tenant.id, tenant_role=TENANT_MEMBER),
            ]
        )
        set_tenant(db, tenant.id)

        company = OrgUnit(tenant_id=tenant.id, kind="company", name="데모 주식회사")
        db.add(company)
        db.flush()
        division = OrgUnit(
            tenant_id=tenant.id, parent_id=company.id, kind="division", name="개발본부"
        )
        db.add(division)
        db.flush()
        db.add(OrgUnit(tenant_id=tenant.id, parent_id=division.id, kind="team", name="플랫폼팀"))

        system_id = uuid.uuid4()
        system = ProcessSystem(
            id=system_id,
            tenant_id=tenant.id,
            org_unit_id=company.id,
            root_system_id=system_id,
            slug="ims",
            name="통합경영체계",
            description="회사 기준선 체계",
            created_by=admin.id,
        )
        db.add(system)
        db.flush()
        db.add_all(
            [
                RoleAssignment(tenant_id=tenant.id, user_id=owner.id, role="process_owner"),
                RoleAssignment(tenant_id=tenant.id, user_id=qmr.id, role="qmr"),
            ]
        )
        db.flush()

        def create(doc_type: str, parent=None, scope_code=None):
            content = _DEMO_DOCS[doc_type]
            doc = doc_service.create_document(
                db,
                system=system,
                payload=DocumentIn(
                    doc_type=doc_type,
                    title=content["title"],
                    scope_code=scope_code,
                    parent_id=parent.id if parent else None,
                ),
                actor_id=owner.id,
            )
            _fill(db, doc.id, content)
            return doc

        def submit(doc):
            return doc_service.submit(
                db, revision=doc_service.open_revision(db, doc.id), actor_id=owner.id
            )

        def approve(doc):
            doc_service.approve(
                db, revision=submit(doc), actor_id=qmr.id, comment="", tenant=tenant
            )

        # 정책·절차는 승인, 지침은 검토 중, 템플릿은 초안 상태로 둔다.
        pol = create("POL", scope_code="QMS")
        approve(pol)
        pro = create("PRO", parent=pol)
        approve(pro)
        wi = create("WI", parent=pro)
        submit(wi)
        create("TMP", parent=wi)

        db.commit()
        print("데모 회사 생성 완료: /demo")
        print("사용자: admin@example.com, owner@example.com, qmr@example.com, member@example.com")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    sub.add_parser("seed").set_defaults(func=cmd_seed)

    p = sub.add_parser("create-user")
    p.add_argument("email")
    p.add_argument("name")
    p.add_argument("--platform-role", choices=["platform_admin", "consultant"])
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("login-link")
    p.add_argument("email")
    p.set_defaults(func=cmd_login_link)

    sub.add_parser("demo").set_defaults(func=cmd_demo)

    p = sub.add_parser("purge-tenant")
    p.add_argument("slug")
    p.add_argument("--actor", required=True, help="삭제 기록에 남길 사용자 이메일")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_purge_tenant)
    p = sub.add_parser("openapi")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_openapi)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
