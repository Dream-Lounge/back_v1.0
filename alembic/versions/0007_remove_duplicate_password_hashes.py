"""remove duplicate password hashes for Supabase-linked users

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET password_hash = '!supabase-auth-only' "
        "WHERE auth_user_id IS NOT NULL"
    )


def downgrade() -> None:
    # 원래 비밀번호 해시는 복구할 수 없으며 복구해서도 안 된다.
    pass
