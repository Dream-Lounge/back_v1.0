"""snapshot submitted application forms

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-06 21:06:49.186442

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017'
down_revision: Union[str, None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("form_snapshot", sa.JSON(), nullable=True),
    )
    # 기존 제출 건은 현재 DB에 남아 있는 문항 상태를 기준으로 최초 스냅샷을 만든다.
    # 과거에 이미 덮어쓴 문항 내용까지 복원할 수는 없지만, 이 시점 이후 변경은 분리된다.
    op.execute(
        sa.text(
            """
            UPDATE applications AS a
            SET form_snapshot = json_build_object(
                'id', f.id,
                'title', f.title,
                'questions', COALESCE((
                    SELECT json_agg(json_build_object(
                        'id', q.id,
                        'question_text', q.question_text,
                        'question_type', q.question_type,
                        'is_required', q.is_required,
                        'order_index', q.order_index,
                        'options', q.options
                    ) ORDER BY q.order_index)
                    FROM form_questions AS q
                    WHERE q.form_id = f.id
                ), '[]'::json)
            )
            FROM application_forms AS f
            WHERE a.form_id = f.id AND a.is_draft = false
            """
        )
    )


def downgrade() -> None:
    op.drop_column("applications", "form_snapshot")
