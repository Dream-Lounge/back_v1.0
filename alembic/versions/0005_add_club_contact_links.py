"""add multiple club contact links

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clubs",
        sa.Column(
            "contact_links",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE clubs
        SET contact_links =
            CASE
                WHEN contact_email IS NOT NULL AND btrim(contact_email) <> ''
                THEN jsonb_build_array(jsonb_build_object(
                    'type', 'email', 'label', '이메일', 'value', contact_email
                ))
                ELSE '[]'::jsonb
            END
            || CASE
                WHEN contact_phone IS NOT NULL AND btrim(contact_phone) <> ''
                THEN jsonb_build_array(jsonb_build_object(
                    'type', 'phone', 'label', '전화번호', 'value', contact_phone
                ))
                ELSE '[]'::jsonb
            END
            || CASE
                WHEN open_chat_url IS NOT NULL AND btrim(open_chat_url) <> ''
                THEN jsonb_build_array(jsonb_build_object(
                    'type', 'url', 'label', '오픈채팅', 'value', open_chat_url
                ))
                ELSE '[]'::jsonb
            END
        """
    )


def downgrade() -> None:
    op.drop_column("clubs", "contact_links")
