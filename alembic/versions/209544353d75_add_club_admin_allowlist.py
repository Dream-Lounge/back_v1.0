"""add_club_admin_allowlist

Revision ID: 209544353d75
Revises: 0020
Create Date: 2026-09-13 16:58:26.524547

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '209544353d75'
down_revision: Union[str, None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "club_admins",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # Supabase Data API 역할에서는 관리자 허용 목록을 읽거나 변경할 수 없다.
    # 백엔드 제한 계정은 권한 판정을 위한 SELECT만 허용한다.
    op.execute("ALTER TABLE public.club_admins ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE public.club_admins FROM PUBLIC, anon, authenticated")
    op.execute("GRANT SELECT ON TABLE public.club_admins TO dreamlounge_backend")
    op.execute(
        """
        CREATE POLICY dreamlounge_backend_read_club_admins
        ON public.club_admins
        FOR SELECT
        TO dreamlounge_backend
        USING (true)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS dreamlounge_backend_read_club_admins "
        "ON public.club_admins"
    )
    op.execute("REVOKE SELECT ON TABLE public.club_admins FROM dreamlounge_backend")
    op.drop_table("club_admins")
