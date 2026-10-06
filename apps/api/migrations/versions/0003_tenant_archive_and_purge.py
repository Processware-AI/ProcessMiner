"""tenant archive, purge function, deletion tombstone

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APP_ROLE = "pm_app"


def upgrade() -> None:
    op.add_column("tenant", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenant", sa.Column("archived_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tenant_archived_by_app_user"),
        "tenant",
        "app_user",
        ["archived_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "deleted_tenant",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.Column("deleted_by_email", sa.String(length=320), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deleted_tenant")),
    )
    # 삭제 흔적은 purge_tenant() 만 쓴다.
    op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON deleted_tenant FROM {APP_ROLE}")

    # 승인판 보호 트리거에 예외를 하나 둔다: 회사 완전 삭제.
    # 조건은 둘 다 맞아야 한다. (1) 그 회사를 지우는 중이라는 표시가 있고,
    # (2) 실행 주체가 테이블 소유자다. 애플리케이션 역할은 purge_tenant() 안에서만
    # 소유자 권한으로 실행되므로, 표시만 흉내 내서는 승인판을 지울 수 없다.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION document_revision_guard() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              IF current_setting('app.purging_tenant', true) = OLD.tenant_id::text
                 AND current_user = (
                   SELECT tableowner FROM pg_tables
                   WHERE schemaname = 'public' AND tablename = 'document_revision'
                 )
              THEN
                RETURN OLD;
              END IF;
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

    # 회사와 그에 딸린 모든 데이터를 지운다. 보관된 회사만 지울 수 있다.
    # 소유자 권한으로 실행되어(SECURITY DEFINER) 감사 기록까지 지울 수 있고,
    # 애플리케이션 역할이 이 함수 밖에서 감사 기록을 지울 방법은 여전히 없다.
    op.execute(
        """
        CREATE FUNCTION purge_tenant(target uuid, actor uuid) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
          t tenant%ROWTYPE;
          actor_email text;
          member_ids uuid[];
          stats jsonb;
          n_users integer;
        BEGIN
          SELECT * INTO t FROM tenant WHERE id = target FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'tenant not found' USING ERRCODE = 'no_data_found';
          END IF;
          IF t.archived_at IS NULL THEN
            RAISE EXCEPTION 'tenant must be archived before it can be purged'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
          SELECT email INTO actor_email FROM app_user WHERE id = actor;
          IF actor_email IS NULL THEN
            RAISE EXCEPTION 'actor not found' USING ERRCODE = 'no_data_found';
          END IF;

          PERFORM set_config('app.purging_tenant', target::text, true);
          SELECT array_agg(user_id) INTO member_ids FROM membership WHERE tenant_id = target;

          stats := jsonb_build_object(
            'documents', (SELECT count(*) FROM document WHERE tenant_id = target),
            'revisions', (SELECT count(*) FROM document_revision WHERE tenant_id = target),
            'systems', (SELECT count(*) FROM process_system WHERE tenant_id = target),
            'org_units', (SELECT count(*) FROM org_unit WHERE tenant_id = target),
            'members', coalesce(array_length(member_ids, 1), 0),
            'audit_entries', (SELECT count(*) FROM audit_log WHERE tenant_id = target),
            'last_audit_hash', (
              SELECT hash FROM audit_log WHERE tenant_id = target ORDER BY id DESC LIMIT 1
            )
          );

          DELETE FROM audit_log WHERE tenant_id = target;
          DELETE FROM document_link WHERE tenant_id = target;
          DELETE FROM document_revision WHERE tenant_id = target;
          -- 자기 참조(상위 문서·상위 체계·상위 조직)는 말단부터 지운다.
          LOOP
            DELETE FROM document d WHERE d.tenant_id = target
              AND NOT EXISTS (SELECT 1 FROM document c WHERE c.parent_id = d.id);
            EXIT WHEN NOT FOUND;
          END LOOP;
          DELETE FROM doc_sequence WHERE tenant_id = target;
          DELETE FROM role_assignment WHERE tenant_id = target;
          LOOP
            DELETE FROM process_system s WHERE s.tenant_id = target
              AND NOT EXISTS (SELECT 1 FROM process_system c WHERE c.parent_system_id = s.id);
            EXIT WHEN NOT FOUND;
          END LOOP;
          LOOP
            DELETE FROM org_unit o WHERE o.tenant_id = target
              AND NOT EXISTS (SELECT 1 FROM org_unit c WHERE c.parent_id = o.id);
            EXIT WHEN NOT FOUND;
          END LOOP;
          DELETE FROM scope_code WHERE tenant_id = target;
          DELETE FROM membership WHERE tenant_id = target;
          DELETE FROM tenant WHERE id = target;

          -- 이 회사에만 속했던 계정은 함께 지운다. 플랫폼 역할이 있거나, 다른 회사에 속했거나,
          -- 다른 회사의 기록에 이름이 남아 있으면 지우지 않는다(그 회사의 이력이 깨지지 않게).
          DELETE FROM app_user u
          WHERE u.id = ANY (coalesce(member_ids, '{}'))
            AND u.id <> actor
            AND u.platform_role IS NULL
            AND NOT EXISTS (SELECT 1 FROM membership m WHERE m.user_id = u.id)
            AND NOT EXISTS (SELECT 1 FROM audit_log a WHERE a.actor_id = u.id)
            AND NOT EXISTS (
              SELECT 1 FROM document_revision r WHERE r.author_id = u.id OR r.reviewer_id = u.id
            );
          GET DIAGNOSTICS n_users = ROW_COUNT;
          stats := stats || jsonb_build_object('accounts_removed', n_users);

          INSERT INTO deleted_tenant
            (id, tenant_id, slug, name, deleted_by, deleted_by_email, summary)
          VALUES (gen_random_uuid(), target, t.slug, t.name, actor, actor_email, stats);

          RETURN stats;
        END $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION purge_tenant(uuid, uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION purge_tenant(uuid, uuid) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_tenant(uuid, uuid)")
    # 트리거 함수는 0002 의 정의로 되돌리지 않는다. 예외 조건은 purge_tenant() 없이는 쓰이지 않는다.
    op.drop_table("deleted_tenant")
    op.drop_constraint(op.f("fk_tenant_archived_by_app_user"), "tenant", type_="foreignkey")
    op.drop_column("tenant", "archived_by")
    op.drop_column("tenant", "archived_at")
