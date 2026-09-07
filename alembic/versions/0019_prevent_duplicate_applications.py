"""prevent duplicate applications

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-06 22:38:07.088691

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 사전 조회만으로는 동시에 들어온 두 요청을 막을 수 없으므로 DB가
    # 폼별 사용자 신청서를 하나만 허용하도록 원자적으로 보장한다.
    op.drop_index(
        "uq_applications_one_draft_per_user_form",
        table_name="applications",
    )
    op.create_unique_constraint(
        "uq_applications_form_user",
        "applications",
        ["form_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_applications_form_user",
        "applications",
        type_="unique",
    )
    op.create_index(
        "uq_applications_one_draft_per_user_form",
        "applications",
        ["form_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("is_draft IS TRUE"),
    )
