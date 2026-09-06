"""soft delete form questions

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_questions",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_form_questions_active", "form_questions", ["form_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_form_questions_active", table_name="form_questions")
    op.drop_column("form_questions", "is_active")
