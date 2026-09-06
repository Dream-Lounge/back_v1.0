"""add club tagline

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clubs", sa.Column("tagline", sa.String(length=500), nullable=True))
    # 이전 프론트는 소개글을 description에 저장했으므로 기존 내용을 보존한다.
    op.execute("UPDATE clubs SET tagline = LEFT(description, 500) WHERE description IS NOT NULL")


def downgrade() -> None:
    op.drop_column("clubs", "tagline")
