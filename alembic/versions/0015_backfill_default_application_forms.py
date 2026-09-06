"""backfill default application forms

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO application_forms
            (id, club_id, title, is_active, created_at, updated_at)
        SELECT
            gen_random_uuid()::text,
            clubs.id,
            clubs.name || ' 지원서',
            true,
            NOW(),
            NOW()
        FROM clubs
        WHERE NOT EXISTS (
            SELECT 1
            FROM application_forms
            WHERE application_forms.club_id = clubs.id
              AND application_forms.is_active = true
        )
        """
    )


def downgrade() -> None:
    # 자동 생성 이후 관리자가 문항이나 지원서를 연결했을 수 있으므로
    # 데이터 손실을 막기 위해 downgrade에서 폼을 임의 삭제하지 않는다.
    pass
