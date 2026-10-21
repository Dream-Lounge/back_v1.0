"""add email verification timestamp and club admin role

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        "UPDATE users SET email_verified_at = COALESCE(updated_at, created_at, now()) "
        "WHERE email_verified IS TRUE AND email_verified_at IS NULL"
    )

    op.drop_constraint("ck_club_members_role", "club_members", type_="check")
    op.create_check_constraint(
        "ck_club_members_role",
        "club_members",
        "role IN ('president', 'admin', 'member')",
    )


def downgrade() -> None:
    # admin을 member로 되돌려 기존 제약조건을 안전하게 복원한다.
    op.execute("UPDATE club_members SET role = 'member' WHERE role = 'admin'")
    op.drop_constraint("ck_club_members_role", "club_members", type_="check")
    op.create_check_constraint(
        "ck_club_members_role",
        "club_members",
        "role IN ('president', 'member')",
    )
    op.drop_column("users", "email_verified_at")
