"""add onboarding, interests, consent versions and audit logs

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pending_email", sa.String(255), nullable=True))
    op.add_column(
        "users", sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True)
    )
    op.create_index("uq_users_pending_email", "users", ["pending_email"], unique=True)

    op.add_column(
        "privacy_consents",
        sa.Column(
            "policy_version",
            sa.String(50),
            nullable=False,
            server_default="legacy",
        ),
    )

    op.create_table(
        "user_interests",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("tag_key", sa.String(50), nullable=False),
        sa.Column("tag_value", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "tag_key", "tag_value", name="uq_user_interests_value"
        ),
    )
    op.create_index("ix_user_interests_user_id", "user_interests", ["user_id"])
    op.create_index(
        "ix_user_interests_tag_lookup", "user_interests", ["tag_key", "tag_value"]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_action_created", "audit_logs", ["action", "created_at"]
    )

    # Data API 직접 접근은 닫고 FastAPI 전용 런타임 역할에만 최소 권한을 준다.
    for table in ("user_interests", "audit_logs"):
        op.execute(sa.text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated'))

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_interests "
        "TO dreamlounge_backend"
    )
    op.execute(
        "CREATE POLICY dreamlounge_backend_access ON public.user_interests "
        "FOR ALL TO dreamlounge_backend USING (true) WITH CHECK (true)"
    )
    op.execute(
        "GRANT SELECT, INSERT ON TABLE public.audit_logs TO dreamlounge_backend"
    )
    op.execute(
        "CREATE POLICY dreamlounge_backend_access ON public.audit_logs "
        "FOR ALL TO dreamlounge_backend USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS dreamlounge_backend_access ON public.audit_logs"
    )
    op.execute(
        "DROP POLICY IF EXISTS dreamlounge_backend_access ON public.user_interests"
    )
    op.execute(
        "REVOKE SELECT, INSERT ON TABLE public.audit_logs FROM dreamlounge_backend"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_interests "
        "FROM dreamlounge_backend"
    )
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_user_interests_tag_lookup", table_name="user_interests")
    op.drop_index("ix_user_interests_user_id", table_name="user_interests")
    op.drop_table("user_interests")
    op.drop_column("privacy_consents", "policy_version")
    op.drop_index("uq_users_pending_email", table_name="users")
    op.drop_column("users", "onboarding_completed_at")
    op.drop_column("users", "pending_email")
