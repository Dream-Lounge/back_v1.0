"""expand club tagline to 2000 characters

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "clubs",
        "tagline",
        existing_type=sa.String(length=500),
        type_=sa.String(length=2000),
        existing_nullable=True,
    )


def downgrade() -> None:
    # 500자를 넘는 기존 데이터가 있어도 롤백이 실패하지 않도록 먼저 줄인다.
    op.execute("UPDATE clubs SET tagline = LEFT(tagline, 500) WHERE LENGTH(tagline) > 500")
    op.alter_column(
        "clubs",
        "tagline",
        existing_type=sa.String(length=2000),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
