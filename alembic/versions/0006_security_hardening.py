"""harden public data access and authentication controls

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PUBLIC_TABLES = (
    "alembic_version",
    "application_answers",
    "application_forms",
    "applications",
    "auth_rate_limits",
    "club_members",
    "club_tags",
    "clubs",
    "comments",
    "email_verifications",
    "form_questions",
    "notifications",
    "posts",
    "privacy_consents",
    "users",
)


def upgrade() -> None:
    op.alter_column(
        "email_verifications",
        "code",
        existing_type=sa.String(length=10),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        "email_verifications",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "auth_rate_limits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_rate_limits_lookup",
        "auth_rate_limits",
        ["action", "subject_hash", "created_at"],
    )
    op.create_index(
        "ix_auth_rate_limits_ip_lookup",
        "auth_rate_limits",
        ["action", "ip_hash", "created_at"],
    )

    # 관계 무결성과 권한 판정에서 사용하는 중복 상태를 DB에서도 차단한다.
    op.create_index(
        "uq_application_answers_application_question",
        "application_answers",
        ["application_id", "question_id"],
        unique=True,
    )
    op.create_index("ix_application_answers_question_id", "application_answers", ["question_id"])
    op.create_index(
        "uq_application_forms_one_active_per_club",
        "application_forms",
        ["club_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "uq_applications_one_draft_per_user_form",
        "applications",
        ["form_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("is_draft IS TRUE"),
    )
    op.create_index("ix_applications_user_id", "applications", ["user_id"])
    op.create_index(
        "uq_club_members_one_active_membership",
        "club_members",
        ["club_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_club_members_one_active_president",
        "club_members",
        ["club_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND role = 'president'"),
    )
    op.create_index("ix_club_members_user_id", "club_members", ["user_id"])
    op.create_index("ix_club_tags_club_id", "club_tags", ["club_id"])
    op.create_index("ix_clubs_president_id", "clubs", ["president_id"])
    op.create_index("ix_comments_author_id", "comments", ["author_id"])
    op.create_index("ix_comments_post_id", "comments", ["post_id"])
    op.create_index("ix_form_questions_form_id", "form_questions", ["form_id"])
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])
    op.create_index("ix_posts_author_id", "posts", ["author_id"])
    op.create_index("ix_posts_club_id", "posts", ["club_id"])
    op.create_index(
        "uq_privacy_consents_user_id", "privacy_consents", ["user_id"], unique=True
    )

    op.create_check_constraint(
        "ck_applications_status",
        "applications",
        "status IN ('draft', 'submitted', 'pending', 'passed', 'failed')",
    )
    op.create_check_constraint(
        "ck_club_members_role", "club_members", "role IN ('president', 'member')"
    )
    op.create_check_constraint(
        "ck_club_members_status", "club_members", "status IN ('active', 'withdrawn')"
    )

    # 프론트는 FastAPI만 사용하므로 Data API 직접 권한을 완전히 닫는다.
    for table in PUBLIC_TABLES:
        op.execute(sa.text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM anon, authenticated")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated")
    op.execute("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        "REVOKE ALL ON TABLES FROM anon, authenticated"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        "REVOKE ALL ON SEQUENCES FROM anon, authenticated"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        "REVOKE EXECUTE ON FUNCTIONS FROM anon, authenticated"
    )


def downgrade() -> None:
    for table in PUBLIC_TABLES:
        op.execute(sa.text(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY'))
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO anon, authenticated")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated")

    op.drop_constraint("ck_club_members_status", "club_members", type_="check")
    op.drop_constraint("ck_club_members_role", "club_members", type_="check")
    op.drop_constraint("ck_applications_status", "applications", type_="check")
    op.drop_index("uq_privacy_consents_user_id", table_name="privacy_consents")
    op.drop_index("ix_posts_club_id", table_name="posts")
    op.drop_index("ix_posts_author_id", table_name="posts")
    op.drop_index("ix_notifications_recipient_id", table_name="notifications")
    op.drop_index("ix_form_questions_form_id", table_name="form_questions")
    op.drop_index("ix_comments_post_id", table_name="comments")
    op.drop_index("ix_comments_author_id", table_name="comments")
    op.drop_index("ix_clubs_president_id", table_name="clubs")
    op.drop_index("ix_club_tags_club_id", table_name="club_tags")
    op.drop_index("ix_club_members_user_id", table_name="club_members")
    op.drop_index("uq_club_members_one_active_president", table_name="club_members")
    op.drop_index("uq_club_members_one_active_membership", table_name="club_members")
    op.drop_index("ix_applications_user_id", table_name="applications")
    op.drop_index("uq_applications_one_draft_per_user_form", table_name="applications")
    op.drop_index("uq_application_forms_one_active_per_club", table_name="application_forms")
    op.drop_index("ix_application_answers_question_id", table_name="application_answers")
    op.drop_index("uq_application_answers_application_question", table_name="application_answers")
    op.drop_index("ix_auth_rate_limits_ip_lookup", table_name="auth_rate_limits")
    op.drop_index("ix_auth_rate_limits_lookup", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
    op.drop_column("email_verifications", "attempt_count")
    op.alter_column(
        "email_verifications",
        "code",
        existing_type=sa.String(length=64),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
