"""add per-user guide hidden-until timestamp

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("guide_hidden_until", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "guide_hidden_until")
