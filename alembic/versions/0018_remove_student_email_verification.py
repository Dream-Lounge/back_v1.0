"""remove student email verification

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-06 21:39:19.216067

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 간소화 버전은 이메일 인증을 사용하지 않는다. 기존 인증번호와
    # 확인 토큰은 더 이상 필요하지 않으므로 전용 테이블을 제거한다.
    op.drop_table("email_verifications")


def downgrade() -> None:
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmation_token_hash", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_verifications_email",
        "email_verifications",
        ["email"],
    )
    op.create_index(
        "ix_email_verifications_confirmation_lookup",
        "email_verifications",
        ["email", "confirmation_token_hash", "expires_at"],
    )
    op.execute("ALTER TABLE public.email_verifications ENABLE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE public.email_verifications "
        "FROM anon, authenticated"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.email_verifications "
        "TO dreamlounge_backend"
    )
    op.execute(
        "CREATE POLICY dreamlounge_backend_access "
        "ON public.email_verifications FOR ALL TO dreamlounge_backend "
        "USING (true) WITH CHECK (true)"
    )
