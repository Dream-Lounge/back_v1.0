"""Read-only verification for the simplified production database."""

from pathlib import Path

from sqlalchemy import create_engine, text

from migrate_club_catalog import database_url


def scalar(connection, sql: str):
    return connection.execute(text(sql)).scalar_one()


def main() -> None:
    engine = create_engine(
        database_url(Path(__file__).resolve().parents[1] / ".env"),
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
        print(f"alembic={version}")
        print("counts=" + ",".join(f"{key}:{value}" for key, value in counts.items()))
        print(f"rls_missing={list(rls_missing)}")
        print(f"anon_authenticated_table_grants={exposed_grants}")
        print(f"backend_policy_tables={backend_policy_tables}")
        if version != "0013" or rls_missing or exposed_grants:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
