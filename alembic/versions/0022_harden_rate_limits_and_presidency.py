"""harden device rate limits and one-club presidency

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auth_rate_limits",
        sa.Column("device_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_auth_rate_limits_device_lookup",
        "auth_rate_limits",
        ["action", "device_hash", "created_at"],
    )

    # 관리자 한 명이 API를 직접 호출해 여러 동아리 회장이 되는 것도
    # DB에서 원자적으로 차단한다. 기존 중복 데이터가 있으면 조용히
    # 하나를 선택하지 않고 운영자가 먼저 정리하도록 마이그레이션을 중단한다.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT user_id
                FROM public.club_members
                WHERE status = 'active' AND role = 'president'
                GROUP BY user_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION '한 사용자가 여러 동아리의 활성 회장으로 등록되어 있습니다.';
            END IF;
        END
        $$
        """
    )
    op.create_index(
        "uq_club_members_one_active_presidency_per_user",
        "club_members",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND role = 'president'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_club_members_one_active_presidency_per_user",
        table_name="club_members",
    )
    op.drop_index("ix_auth_rate_limits_device_lookup", table_name="auth_rate_limits")
    op.drop_column("auth_rate_limits", "device_hash")
