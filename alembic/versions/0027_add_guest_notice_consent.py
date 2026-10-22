"""add guest application limitation notice consent

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("guest_notice_agreed_at", sa.DateTime(), nullable=True),
    )
    # 이미 저장된 비회원 신청서는 제출 시 안내를 확인한 기존 데이터로 간주한다.
    op.execute(
        "UPDATE applications SET guest_notice_agreed_at = submitted_at "
        "WHERE applicant_type = 'guest' AND guest_notice_agreed_at IS NULL"
    )
    op.create_check_constraint(
        "ck_applications_guest_notice_consent",
        "applications",
        "(applicant_type = 'member' AND guest_notice_agreed_at IS NULL) OR "
        "(applicant_type = 'guest' AND guest_notice_agreed_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_applications_guest_notice_consent",
        "applications",
        type_="check",
    )
    op.drop_column("applications", "guest_notice_agreed_at")
