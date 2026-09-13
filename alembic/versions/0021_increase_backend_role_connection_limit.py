"""increase backend role connection limit

Revision ID: 0021
Revises: 209544353d75
Create Date: 2026-09-13

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "209544353d75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DigitalOcean 컨테이너 2개 × (pool 12 + overflow 8) = 최대 40개.
    # 배포 교체 중의 짧은 중첩을 허용하되 Supabase Micro 전체 연결 여유를 남긴다.
    op.execute("ALTER ROLE dreamlounge_backend CONNECTION LIMIT 50")


def downgrade() -> None:
    op.execute("ALTER ROLE dreamlounge_backend CONNECTION LIMIT 10")
