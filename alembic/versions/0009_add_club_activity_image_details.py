"""add normalized club activity image details

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "club_activity_images",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("club_id", sa.String(length=36), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=False),
        sa.Column("caption", sa.String(length=200), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("order_index >= 0", name="ck_club_activity_images_order"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "club_id", "order_index", name="uq_club_activity_images_order"
        ),
    )
    op.create_index(
        "ix_club_activity_images_club_id",
        "club_activity_images",
        ["club_id"],
    )

    # 기존 JSON URL 배열을 순서와 함께 새 테이블로 옮긴다. 기존 컬럼은
    # 현재 프론트 계약(string[])을 유지하기 위해 제거하지 않는다.
    op.execute(
        """
        INSERT INTO club_activity_images
            (id, club_id, image_url, caption, order_index, created_at, updated_at)
        SELECT
            gen_random_uuid()::text,
            clubs.id,
            image.value,
            NULL,
            image.ordinality - 1,
            NOW(),
            NOW()
        FROM clubs
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE
                WHEN jsonb_typeof(clubs.activity_images::jsonb) = 'array'
                    THEN clubs.activity_images::jsonb
                ELSE '[]'::jsonb
            END
        ) WITH ORDINALITY AS image(value, ordinality)
        """
    )

    # 브라우저에서는 Data API를 사용하지 않으므로 새 테이블도 직접 접근을 막는다.
    op.execute("ALTER TABLE public.club_activity_images ENABLE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE public.club_activity_images FROM anon, authenticated"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_club_activity_images_club_id",
        table_name="club_activity_images",
    )
    op.drop_table("club_activity_images")
