"""add restricted database role for backend runtime

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APP_TABLES = (
    "application_answers",
    "application_forms",
    "applications",
    "auth_rate_limits",
    "club_activity_images",
    "club_members",
    "club_tags",
    "clubs",
    "comments",
    "email_verifications",
    "form_questions",
    "notifications",
    "posts",
    "privacy_consents",
    "users",
)


def upgrade() -> None:
    # 비밀번호는 마이그레이션/저장소에 남기지 않는다. 배포 담당자가 Supabase에서
    # ALTER ROLE ... PASSWORD로 설정한 뒤 DATABASE_URL에만 보관한다.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dreamlounge_backend') THEN
                CREATE ROLE dreamlounge_backend
                    LOGIN
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE
                    NOREPLICATION
                    NOBYPASSRLS
                    CONNECTION LIMIT 10;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO dreamlounge_backend")

    for table in APP_TABLES:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table}" '
            "TO dreamlounge_backend"
        )
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_policies
                    WHERE schemaname = 'public'
                      AND tablename = '{table}'
                      AND policyname = 'dreamlounge_backend_access'
                ) THEN
                    CREATE POLICY dreamlounge_backend_access
                    ON public."{table}"
                    FOR ALL
                    TO dreamlounge_backend
                    USING (true)
                    WITH CHECK (true);
                END IF;
            END
            $$
            """
        )

    op.execute("ALTER ROLE dreamlounge_backend SET statement_timeout = '15s'")
    op.execute("ALTER ROLE dreamlounge_backend SET lock_timeout = '5s'")
    op.execute(
        "ALTER ROLE dreamlounge_backend SET idle_in_transaction_session_timeout = '30s'"
    )


def downgrade() -> None:
    for table in reversed(APP_TABLES):
        op.execute(
            f'DROP POLICY IF EXISTS dreamlounge_backend_access ON public."{table}"'
        )
        op.execute(
            f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table}" '
            "FROM dreamlounge_backend"
        )
    op.execute("REVOKE USAGE ON SCHEMA public FROM dreamlounge_backend")
    op.execute("DROP ROLE IF EXISTS dreamlounge_backend")
