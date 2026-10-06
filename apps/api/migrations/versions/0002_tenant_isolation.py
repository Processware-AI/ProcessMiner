"""tenant isolation, app role grants, revision immutability

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "pm_app"
# 이 리비전 시점의 회사별 격리 대상. 이후 추가되는 테이블은 각자의 마이그레이션에서 처리한다.
TENANT_TABLES = [
    "org_unit",
    "process_system",
    "role_assignment",
    "document",
    "document_revision",
    "document_link",
    "doc_sequence",
    "audit_log",
]
READ_ONLY_TABLES = ["doc_type_def", "standard_def"]


def upgrade() -> None:
    # 개발 환경은 docker/postgres/init.sql 이 로그인 가능한 역할로 먼저 만든다.
    # 없는 환경에서는 권한을 받을 역할만 만들어 두고, 로그인 설정은 운영자가 한다.
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} NOLOGIN;
          END IF;
        END $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    # 감사 기록은 추가만 가능하다.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {APP_ROLE}")
    # 참조 데이터는 적재기(소유자 역할)만 바꾼다.
    for table in READ_ONLY_TABLES:
        op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {table} FROM {APP_ROLE}")

    # 현재 요청의 회사. 설정되지 않았으면 NULL 이므로 어떤 행과도 일치하지 않는다.
    op.execute(
        """
        CREATE FUNCTION app_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;
        """
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = app_current_tenant())
              WITH CHECK (tenant_id = app_current_tenant());
            """
        )

    # 영역코드: 공통 코드(tenant_id 없음)는 누구나 읽고, 회사 코드는 그 회사만 읽고 쓴다.
    op.execute("ALTER TABLE scope_code ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY scope_code_read ON scope_code FOR SELECT
          USING (tenant_id IS NULL OR tenant_id = app_current_tenant());
        """
    )
    op.execute(
        """
        CREATE POLICY scope_code_insert ON scope_code FOR INSERT
          WITH CHECK (tenant_id = app_current_tenant());
        """
    )
    op.execute(
        """
        CREATE POLICY scope_code_update ON scope_code FOR UPDATE
          USING (tenant_id = app_current_tenant())
          WITH CHECK (tenant_id = app_current_tenant());
        """
    )
    op.execute(
        """
        CREATE POLICY scope_code_delete ON scope_code FOR DELETE
          USING (tenant_id = app_current_tenant());
        """
    )

    # 승인된 개정판은 내용을 바꿀 수 없다. 허용되는 변화는 approved → superseded 뿐이다.
    op.execute(
        """
        CREATE FUNCTION document_revision_guard() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              RAISE EXCEPTION 'only draft revisions can be deleted'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN OLD;
          END IF;

          IF OLD.status IN ('approved', 'superseded') THEN
            IF NEW.title IS DISTINCT FROM OLD.title
               OR NEW.version IS DISTINCT FROM OLD.version
               OR NEW.sections IS DISTINCT FROM OLD.sections
               OR NEW.structured IS DISTINCT FROM OLD.structured
               OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
               OR NEW.document_id IS DISTINCT FROM OLD.document_id
               OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
               OR NEW.reviewer_id IS DISTINCT FROM OLD.reviewer_id
               OR NEW.author_id IS DISTINCT FROM OLD.author_id
            THEN
              RAISE EXCEPTION 'approved revisions are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status
               AND NOT (OLD.status = 'approved' AND NEW.status = 'superseded')
            THEN
              RAISE EXCEPTION 'invalid status change for an approved revision'
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          END IF;

          NEW.updated_at := now();
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_revision_guard
          BEFORE UPDATE OR DELETE ON document_revision
          FOR EACH ROW EXECUTE FUNCTION document_revision_guard();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS document_revision_guard ON document_revision")
    op.execute("DROP FUNCTION IF EXISTS document_revision_guard()")
    for policy in (
        "scope_code_read",
        "scope_code_insert",
        "scope_code_update",
        "scope_code_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON scope_code")
    op.execute("ALTER TABLE scope_code DISABLE ROW LEVEL SECURITY")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant()")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
