"""prepare simplified production schema

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 회원 없이 기존 동아리 정보만 옮길 때 회장 연결을 비워 둘 수 있다.
    op.alter_column("clubs", "president_id", existing_type=sa.String(36), nullable=True)

    # 신청 당시 정보를 스냅샷으로 보존한다. 사용자 프로필이 나중에 변경되어도
    # 이미 제출된 신청서와 관리자 화면의 정보가 바뀌지 않는다.
    op.add_column("applications", sa.Column("applicant_student_id", sa.String(20), nullable=True))
    op.add_column("applications", sa.Column("applicant_name", sa.String(50), nullable=True))
    op.add_column("applications", sa.Column("applicant_department", sa.String(100), nullable=True))
    op.add_column("applications", sa.Column("applicant_phone", sa.String(20), nullable=True))
    op.add_column("applications", sa.Column("applicant_grade", sa.String(1), nullable=True))
    op.add_column("applications", sa.Column("admin_comment", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE applications AS a
        SET applicant_student_id = u.student_id,
            applicant_name = u.name,
            applicant_department = COALESCE(u.department, ''),
            applicant_phone = COALESCE(u.phone, ''),
            applicant_grade = '1'
        FROM users AS u
        WHERE u.id = a.user_id
        """
    )
    for column in (
        "applicant_student_id",
        "applicant_name",
        "applicant_department",
        "applicant_phone",
        "applicant_grade",
    ):
        op.alter_column("applications", column, nullable=False)
    op.create_check_constraint(
        "ck_applications_applicant_grade", "applications", "applicant_grade IN ('1','2','3','4','5','6')"
    )
    op.create_check_constraint(
        "ck_applications_draft_state",
        "applications",
        "(is_draft AND status = 'draft' AND submitted_at IS NULL) OR "
        "(NOT is_draft AND status <> 'draft' AND submitted_at IS NOT NULL)",
    )
    op.create_index(
        "uq_applications_user_form", "applications", ["form_id", "user_id"], unique=True
    )
    op.create_index(
        "ix_applications_form_submitted",
        "applications",
        ["form_id", "is_draft", "submitted_at"],
    )

    # 자체 JWT refresh token은 원문을 저장하지 않고 HMAC 해시만 보관한다.
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index(
        "ix_auth_sessions_user_active", "auth_sessions", ["user_id", "revoked_at", "expires_at"]
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.execute("ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL PRIVILEGES ON TABLE public.auth_sessions FROM anon, authenticated")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.auth_sessions TO dreamlounge_backend"
    )
    op.execute(
        "CREATE POLICY dreamlounge_backend_access ON public.auth_sessions FOR ALL "
        "TO dreamlounge_backend USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS dreamlounge_backend_access ON public.auth_sessions")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public.auth_sessions FROM dreamlounge_backend"
    )
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_applications_form_submitted", table_name="applications")
    op.drop_index("uq_applications_user_form", table_name="applications")
    op.drop_constraint("ck_applications_draft_state", "applications", type_="check")
    op.drop_constraint("ck_applications_applicant_grade", "applications", type_="check")
    op.drop_column("applications", "admin_comment")
    op.drop_column("applications", "applicant_grade")
    op.drop_column("applications", "applicant_phone")
    op.drop_column("applications", "applicant_department")
    op.drop_column("applications", "applicant_name")
    op.drop_column("applications", "applicant_student_id")
    op.alter_column("clubs", "president_id", existing_type=sa.String(36), nullable=False)
