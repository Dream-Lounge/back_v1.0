"""Read-only verification for the simplified production database."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from migrate_club_catalog import database_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def scalar(connection, sql: str):
    return connection.execute(text(sql)).scalar_one()


def expected_alembic_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic head revision을 찾을 수 없습니다.")
    return head


def main() -> None:
    expected_version = expected_alembic_head()
    engine = create_engine(
        database_url(PROJECT_ROOT / ".env"),
        connect_args={"prepare_threshold": None},
    )
    with engine.connect() as connection:
        version = scalar(connection, "SELECT version_num FROM alembic_version")
        counts = {
            table: scalar(connection, f'SELECT count(*) FROM public."{table}"')
            for table in (
                "clubs",
                "club_tags",
                "club_activity_images",
                "application_forms",
                "form_questions",
                "users",
                "club_members",
                "applications",
            )
        }
        rls_missing = connection.execute(
            text(
                """
                SELECT relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                  AND relname <> 'alembic_version' AND NOT c.relrowsecurity
                ORDER BY relname
                """
            )
        ).scalars().all()
        exposed_grants = scalar(
            connection,
            """
            SELECT count(*) FROM information_schema.role_table_grants
            WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')
            """,
        )
        backend_policy_tables = scalar(
            connection,
            """
            SELECT count(DISTINCT tablename) FROM pg_policies
            WHERE schemaname = 'public' AND policyname = 'dreamlounge_backend_access'
            """,
        )
        submitted_without_snapshot = scalar(
            connection,
            """
            SELECT count(*) FROM public.applications
            WHERE is_draft = false AND form_snapshot IS NULL
            """,
        )
        application_uniqueness_constraints = scalar(
            connection,
            """
            SELECT count(*)
            FROM pg_constraint constraint_info
            JOIN pg_class table_info ON table_info.oid = constraint_info.conrelid
            JOIN pg_namespace namespace_info ON namespace_info.oid = table_info.relnamespace
            WHERE namespace_info.nspname = 'public'
              AND table_info.relname = 'applications'
              AND constraint_info.conname = 'uq_applications_form_user'
              AND constraint_info.contype = 'u'
            """,
        )
        print(f"alembic={version}")
        print(f"expected_alembic={expected_version}")
        print("counts=" + ",".join(f"{key}:{value}" for key, value in counts.items()))
        print(f"rls_missing={list(rls_missing)}")
        print(f"anon_authenticated_table_grants={exposed_grants}")
        print(f"backend_policy_tables={backend_policy_tables}")
        print(f"submitted_without_form_snapshot={submitted_without_snapshot}")
        print(f"application_uniqueness_constraints={application_uniqueness_constraints}")
        if (
            version != expected_version
            or rls_missing
            or exposed_grants
            or submitted_without_snapshot
            or application_uniqueness_constraints != 1
        ):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
