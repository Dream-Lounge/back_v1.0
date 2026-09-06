"""Assign an already registered simplified user as one club's president."""

import argparse
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

from migrate_club_catalog import database_url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--club-id", required=True)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = create_engine(database_url(args.env), connect_args={"prepare_threshold": None})
    with engine.begin() as connection:
        club = connection.execute(
            text("SELECT id, name, president_id FROM clubs WHERE id=:id FOR UPDATE"),
            {"id": args.club_id},
        ).mappings().first()
        user = connection.execute(
            text("SELECT id, student_id FROM users WHERE student_id=:student_id AND is_active"),
            {"student_id": args.student_id},
        ).mappings().first()
        if not club:
            raise RuntimeError("동아리를 찾을 수 없습니다.")
        if not user:
            raise RuntimeError("먼저 해당 학번으로 회원가입해야 합니다.")
        if club["president_id"] and club["president_id"] != user["id"]:
            raise RuntimeError("이미 다른 회장이 지정된 동아리입니다.")

        print(f"지정 예정: {club['name']} <- {user['student_id']}")
        if not args.apply:
            print("DRY RUN: 변경하지 않았습니다.")
            return

        updated = connection.execute(
            text(
                """
                UPDATE club_members
                SET role='president', status='active', left_at=NULL
                WHERE club_id=:club_id AND user_id=:user_id
                """
            ),
            {"club_id": club["id"], "user_id": user["id"]},
        )
        if updated.rowcount == 0:
            connection.execute(
            text(
                """
                INSERT INTO club_members (id, club_id, user_id, role, status, joined_at)
                VALUES (:id, :club_id, :user_id, 'president', 'active', :joined_at)
                """
            ),
            {
                "id": str(uuid4()),
                "club_id": club["id"],
                "user_id": user["id"],
                "joined_at": datetime.utcnow(),
            },
            )
        connection.execute(
            text("UPDATE clubs SET president_id=:user_id WHERE id=:club_id"),
            {"user_id": user["id"], "club_id": club["id"]},
        )
        print("회장 지정 완료")


if __name__ == "__main__":
    main()
