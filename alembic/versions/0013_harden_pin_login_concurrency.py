"""harden PIN login under concurrent traffic

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(), nullable=True))
    op.create_check_constraint(
        "ck_users_failed_login_count", "users", "failed_login_count >= 0"
    )
    op.create_index("ix_users_locked_until", "users", ["locked_until"])
    op.create_index("ix_auth_rate_limits_created_at", "auth_rate_limits", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_created_at", table_name="auth_rate_limits")
    op.drop_index("ix_users_locked_until", table_name="users")
    op.drop_constraint("ck_users_failed_login_count", "users", type_="check")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
