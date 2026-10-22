"""add guest applications, integrated boards and platform roles

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _protect_backend_table(table: str, privileges: str) -> None:
    op.execute(sa.text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated'))
    op.execute(sa.text(f'GRANT {privileges} ON TABLE public."{table}" TO dreamlounge_backend'))
    op.execute(sa.text(
        f'CREATE POLICY dreamlounge_backend_access ON public."{table}" '
        "FOR ALL TO dreamlounge_backend USING (true) WITH CHECK (true)"
    ))


def upgrade() -> None:
    op.add_column("users", sa.Column("guide_seen_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET department = '미입력' WHERE department IS NULL")
    op.alter_column("users", "department", existing_type=sa.String(100), nullable=False)

    op.create_table(
        "platform_roles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("granted_by", sa.String(36), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "role IN ('union_admin', 'developer', 'super_admin')",
            name="ck_platform_roles_role",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_roles_user_active", "platform_roles", ["user_id", "revoked_at"]
    )
    op.create_index(
        "uq_platform_roles_active_user_role",
        "platform_roles",
        ["user_id", "role"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.alter_column("applications", "user_id", existing_type=sa.String(36), nullable=True)
    op.add_column(
        "applications",
        sa.Column("applicant_type", sa.String(20), nullable=False, server_default="member"),
    )
    op.add_column("applications", sa.Column("applicant_email", sa.String(255), nullable=True))
    op.add_column(
        "applications", sa.Column("privacy_policy_version", sa.String(50), nullable=True)
    )
    op.add_column("applications", sa.Column("privacy_agreed_at", sa.DateTime(), nullable=True))
    op.add_column("applications", sa.Column("accepted_at", sa.DateTime(), nullable=True))
    op.add_column("applications", sa.Column("link_expires_at", sa.DateTime(), nullable=True))
    op.add_column("applications", sa.Column("linked_user_id", sa.String(36), nullable=True))
    op.add_column("applications", sa.Column("linked_at", sa.DateTime(), nullable=True))
    op.add_column("applications", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("applications", sa.Column("deleted_by", sa.String(36), nullable=True))
    op.add_column("applications", sa.Column("deletion_reason", sa.String(500), nullable=True))
    op.create_foreign_key(
        "fk_applications_linked_user", "applications", "users", ["linked_user_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_applications_deleted_by", "applications", "users", ["deleted_by"], ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "UPDATE applications AS a SET applicant_email = u.email "
        "FROM users AS u WHERE a.user_id = u.id AND a.applicant_email IS NULL"
    )
    op.execute(
        "UPDATE applications SET privacy_policy_version = 'legacy', "
        "privacy_agreed_at = submitted_at "
        "WHERE is_draft = false AND privacy_policy_version IS NULL"
    )
    op.create_check_constraint(
        "ck_applications_applicant_identity",
        "applications",
        "(applicant_type = 'member' AND user_id IS NOT NULL) OR "
        "(applicant_type = 'guest' AND user_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_applications_link_pair",
        "applications",
        "(linked_user_id IS NULL AND linked_at IS NULL) OR "
        "(linked_user_id IS NOT NULL AND linked_at IS NOT NULL)",
    )
    op.create_index(
        "uq_applications_guest_form_student_active",
        "applications",
        ["form_id", "applicant_student_id"],
        unique=True,
        postgresql_where=sa.text("applicant_type = 'guest' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_applications_admin_listing",
        "applications",
        ["form_id", "applicant_type", "deleted_at", "status", "submitted_at"],
    )
    op.create_index(
        "ix_applications_guest_link_lookup",
        "applications",
        ["applicant_type", "status", "applicant_student_id", "applicant_email", "link_expires_at"],
        postgresql_where=sa.text("linked_user_id IS NULL AND deleted_at IS NULL"),
    )

    op.alter_column("posts", "club_id", existing_type=sa.String(36), nullable=True)
    op.add_column(
        "posts", sa.Column("board_scope", sa.String(20), nullable=False, server_default="club")
    )
    op.add_column(
        "posts", sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_check_constraint(
        "ck_posts_board_scope", "posts", "board_scope IN ('global', 'service', 'club')"
    )
    op.create_check_constraint(
        "ck_posts_scope_club",
        "posts",
        "(board_scope = 'club' AND club_id IS NOT NULL) OR "
        "(board_scope IN ('global', 'service') AND club_id IS NULL)",
    )
    op.create_index(
        "ix_posts_scope_created", "posts", ["board_scope", "is_deleted", "created_at"]
    )
    op.create_index(
        "ix_posts_club_created", "posts", ["club_id", "is_deleted", "created_at"]
    )

    op.create_table(
        "content_reports",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("reporter_id", sa.String(36), nullable=False),
        sa.Column("post_id", sa.String(36), nullable=True),
        sa.Column("comment_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "(post_id IS NOT NULL AND comment_id IS NULL) OR "
            "(post_id IS NULL AND comment_id IS NOT NULL)",
            name="ck_content_reports_one_target",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'reviewed', 'dismissed')",
            name="ck_content_reports_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_reports_status_created", "content_reports", ["status", "created_at"]
    )

    _protect_backend_table("platform_roles", "SELECT, INSERT, UPDATE")
    _protect_backend_table("content_reports", "SELECT, INSERT, UPDATE")


def downgrade() -> None:
    for table in ("content_reports", "platform_roles"):
        op.execute(sa.text(f'DROP POLICY IF EXISTS dreamlounge_backend_access ON public."{table}"'))
        op.execute(sa.text(f'REVOKE ALL ON TABLE public."{table}" FROM dreamlounge_backend'))

    op.drop_index("ix_content_reports_status_created", table_name="content_reports")
    op.drop_table("content_reports")

    op.drop_index("ix_posts_club_created", table_name="posts")
    op.drop_index("ix_posts_scope_created", table_name="posts")
    op.drop_constraint("ck_posts_scope_club", "posts", type_="check")
    op.drop_constraint("ck_posts_board_scope", "posts", type_="check")
    op.drop_column("posts", "is_anonymous")
    op.drop_column("posts", "board_scope")
    op.alter_column("posts", "club_id", existing_type=sa.String(36), nullable=False)

    op.drop_index("ix_applications_guest_link_lookup", table_name="applications")
    op.drop_index("ix_applications_admin_listing", table_name="applications")
    op.drop_index("uq_applications_guest_form_student_active", table_name="applications")
    op.drop_constraint("ck_applications_link_pair", "applications", type_="check")
    op.drop_constraint("ck_applications_applicant_identity", "applications", type_="check")
    op.drop_constraint("fk_applications_deleted_by", "applications", type_="foreignkey")
    op.drop_constraint("fk_applications_linked_user", "applications", type_="foreignkey")
    for column in (
        "deletion_reason", "deleted_by", "deleted_at", "linked_at", "linked_user_id",
        "link_expires_at", "accepted_at", "privacy_agreed_at", "privacy_policy_version",
        "applicant_email", "applicant_type",
    ):
        op.drop_column("applications", column)
    op.alter_column("applications", "user_id", existing_type=sa.String(36), nullable=False)

    op.drop_index("uq_platform_roles_active_user_role", table_name="platform_roles")
    op.drop_index("ix_platform_roles_user_active", table_name="platform_roles")
    op.drop_table("platform_roles")
    op.alter_column("users", "department", existing_type=sa.String(100), nullable=True)
    op.drop_column("users", "guide_seen_at")
