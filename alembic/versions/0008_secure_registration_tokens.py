"""secure registration confirmation tokens and state constraints

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_verifications",
        sa.Column("confirmation_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "email_verifications",
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_email_verifications_confirmation_lookup",
        "email_verifications",
        ["email", "confirmation_token_hash", "expires_at"],
    )
    # 이전 프론트가 저장한 한글 표시값을 API의 고정 enum 값으로 보존 변환한다.
    op.execute(
        """
        UPDATE form_questions
        SET question_type = CASE question_type
            WHEN '단답형' THEN 'text'
            WHEN '장문형' THEN 'textarea'
            WHEN '객관식 (단일선택)' THEN 'choice'
            ELSE question_type
        END
        WHERE question_type IN ('단답형', '장문형', '객관식 (단일선택)')
        """
    )
    op.create_check_constraint(
        "ck_form_questions_type",
        "form_questions",
        "question_type IN ('text', 'textarea', 'choice', 'multiselect')",
    )
    op.create_check_constraint(
        "ck_posts_type", "posts", "post_type IN ('notice', 'general')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_posts_type", "posts", type_="check")
    op.drop_constraint("ck_form_questions_type", "form_questions", type_="check")
    op.drop_index(
        "ix_email_verifications_confirmation_lookup",
        table_name="email_verifications",
    )
    op.drop_column("email_verifications", "confirmed_at")
    op.drop_column("email_verifications", "confirmation_token_hash")
