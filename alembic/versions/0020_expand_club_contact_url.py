"""expand club contact URL length

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "clubs",
        "open_chat_url",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "clubs",
        "open_chat_url",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
