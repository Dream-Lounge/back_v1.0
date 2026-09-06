"""init: create all tables

Revision ID: 0001
Revises:
Create Date: 2026-05-13

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_student_id", "users", ["student_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # ── privacy_consents ───────────────────────────────────────────────────
    op.create_table(
        "privacy_consents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("required_agreed", sa.Boolean(), nullable=False),
        sa.Column("optional_agreed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("agreed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── email_verifications ────────────────────────────────────────────────
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_verifications_email", "email_verifications", ["email"])

    # ── clubs ──────────────────────────────────────────────────────────────
    op.create_table(
        "clubs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("president_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("club_type", sa.String(20), nullable=True),        # 'department' / 'central'
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("open_chat_url", sa.String(255), nullable=True),
        sa.Column("image_url", sa.String(255), nullable=True),
        sa.Column("division", sa.String(100), nullable=True),
        sa.Column("field", sa.String(100), nullable=True),
        sa.Column("atmosphere", sa.String(100), nullable=True),
        sa.Column("activity_purpose", sa.String(100), nullable=True),
        sa.Column("activity_period", sa.String(100), nullable=True),
        sa.Column("recruit_start", sa.Date(), nullable=True),
        sa.Column("recruit_end", sa.Date(), nullable=True),
        sa.Column("is_recruiting", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["president_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_clubs_name", "clubs", ["name"])

    # ── club_tags ──────────────────────────────────────────────────────────
    op.create_table(
        "club_tags",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("club_id", sa.String(36), nullable=False),
        sa.Column("tag_key", sa.String(50), nullable=False),
        sa.Column("tag_value", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── club_members ───────────────────────────────────────────────────────
    op.create_table(
        "club_members",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("club_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),            # 'president' / 'member'
        sa.Column("status", sa.String(20), nullable=False),          # 'active' / 'withdrawn'
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("left_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── application_forms ──────────────────────────────────────────────────
    op.create_table(
        "application_forms",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("club_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── form_questions ─────────────────────────────────────────────────────
    op.create_table(
        "form_questions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("form_id", sa.String(36), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(20), nullable=False),   # 'text' / 'choice' / 'multiselect'
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["application_forms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── applications ───────────────────────────────────────────────────────
    op.create_table(
        "applications",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("form_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        # 'draft' / 'submitted' / 'pending' / 'passed' / 'failed'
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["form_id"], ["application_forms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── application_answers ────────────────────────────────────────────────
    op.create_table(
        "application_answers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("question_id", sa.String(36), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["form_questions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── posts ──────────────────────────────────────────────────────────────
    op.create_table(
        "posts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("club_id", sa.String(36), nullable=False),
        sa.Column("author_id", sa.String(36), nullable=False),
        sa.Column("post_type", sa.String(20), nullable=False),       # 'notice' / 'general'
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_notice", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── comments ───────────────────────────────────────────────────────────
    op.create_table(
        "comments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("post_id", sa.String(36), nullable=False),
        sa.Column("author_id", sa.String(36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── notifications ──────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("recipient_id", sa.String(36), nullable=False),
        sa.Column("noti_type", sa.String(50), nullable=False),       # 'application_result' / 'new_notice'
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # FK 순서에 맞게 역순으로 삭제
    op.drop_table("notifications")
    op.drop_table("comments")
    op.drop_table("posts")
    op.drop_table("application_answers")
    op.drop_table("applications")
    op.drop_table("form_questions")
    op.drop_table("application_forms")
    op.drop_table("club_members")
    op.drop_table("club_tags")
    op.drop_table("clubs")
    op.drop_index("ix_email_verifications_email", table_name="email_verifications")
    op.drop_table("email_verifications")
    op.drop_table("privacy_consents")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_student_id", table_name="users")
    op.drop_table("users")
