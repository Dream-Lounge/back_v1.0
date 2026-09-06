"""Copy only club catalog/configuration data between Dream Lounge databases.

The script intentionally excludes users, memberships, applications, posts,
comments, notifications, and authentication data. It defaults to a dry run.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import dotenv_values
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


TABLES = (
    "clubs",
    "club_tags",
    "club_activity_images",
    "application_forms",
    "form_questions",
)
FORBIDDEN_TARGET_TABLES = (
    "users",
    "club_members",
    "applications",
    "posts",
    "comments",
)


def database_url(env_file: Path) -> str:
    values = dotenv_values(env_file)
    value = values.get("MIGRATION_DATABASE_URL") or values.get("DATABASE_URL")
    if not value:
        raise RuntimeError(f"DATABASE_URL이 없습니다: {env_file}")
    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+psycopg://", 1)
    return value


def q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def existing_tables(connection) -> set[str]:
    return set(inspect(connection).get_table_names(schema="public"))


def table_columns(connection, table: str) -> list[str]:
    return [column["name"] for column in inspect(connection).get_columns(table, schema="public")]


def row_count(connection, table: str) -> int:
    return connection.execute(text(f"SELECT count(*) FROM public.{q(table)}")).scalar_one()


def copy_table(source, target, table: str) -> int:
    common = [
        column
        for column in table_columns(source, table)
        if column in set(table_columns(target, table))
    ]
    rows = source.execute(
        text(f"SELECT {', '.join(q(column) for column in common)} FROM public.{q(table)}")
    ).mappings().all()
    if not rows:
        return 0

    if table == "clubs" and "president_id" in common:
        rows = [{**dict(row), "president_id": None} for row in rows]
    else:
        rows = [dict(row) for row in rows]

    target_column_types = {
        column["name"]: str(column["type"]).upper()
        for column in inspect(target).get_columns(table, schema="public")
    }
    json_columns = {
        column for column, type_name in target_column_types.items() if "JSON" in type_name
    }
    for row in rows:
        for column in json_columns:
            if column in row and row[column] is not None:
                value = row[column]
                if column == "activity_images" and isinstance(value, list):
                    value = [url for url in value if not str(url).startswith("blob:")]
                row[column] = Jsonb(value)

    column_sql = ", ".join(q(column) for column in common)
    value_sql = ", ".join(f":{column}" for column in common)
    update_columns = [column for column in common if column != "id"]
    update_sql = ", ".join(f"{q(column)} = EXCLUDED.{q(column)}" for column in update_columns)
    statement = (
        f"INSERT INTO public.{q(table)} ({column_sql}) VALUES ({value_sql}) "
        f"ON CONFLICT (id) DO UPDATE SET {update_sql}"
    )
    target.execute(text(statement), rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-env", type=Path, required=True)
    parser.add_argument("--target-env", type=Path, required=True)
    parser.add_argument("--expected-target-ref", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_url = database_url(args.source_env)
    target_url = database_url(args.target_env)
    target_host = make_url(target_url).host or ""
    target_user = make_url(target_url).username or ""
    if args.expected_target_ref not in target_host and args.expected_target_ref not in target_user:
        raise RuntimeError("대상 DB가 지정한 Supabase project-ref와 일치하지 않습니다.")
    if make_url(source_url).host == make_url(target_url).host and make_url(source_url).username == target_user:
        raise RuntimeError("원본 DB와 대상 DB가 같습니다.")

    source_engine = create_engine(source_url, connect_args={"prepare_threshold": None})
    target_engine = create_engine(target_url, connect_args={"prepare_threshold": None})
    with source_engine.connect() as source, target_engine.begin() as target:
        source_tables = existing_tables(source)
        target_tables = existing_tables(target)
        missing = [table for table in TABLES if table not in source_tables or table not in target_tables]
        if missing:
            raise RuntimeError("원본 또는 대상에 필요한 테이블이 없습니다: " + ", ".join(missing))

        occupied = {
            table: row_count(target, table)
            for table in FORBIDDEN_TARGET_TABLES
            if table in target_tables and row_count(target, table) > 0
        }
        if occupied:
            raise RuntimeError(f"대상 DB에 사용자 데이터가 있어 중단합니다: {occupied}")

        counts = {table: row_count(source, table) for table in TABLES}
        print("이전 예정:", ", ".join(f"{table}={count}" for table, count in counts.items()))
        if not args.apply:
            print("DRY RUN: 변경하지 않았습니다. 실제 이전은 --apply를 추가하세요.")
            return

        copied = {table: copy_table(source, target, table) for table in TABLES}
        print("이전 완료:", ", ".join(f"{table}={count}" for table, count in copied.items()))


if __name__ == "__main__":
    main()
