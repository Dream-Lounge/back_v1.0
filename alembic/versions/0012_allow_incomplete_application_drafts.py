"""allow incomplete applicant information only while an application is a draft

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMNS = (
    "applicant_student_id",
    "applicant_name",
    "applicant_department",
    "applicant_phone",
    "applicant_grade",
)


def upgrade() -> None:
    for column in COLUMNS:
        op.alter_column("applications", column, existing_type=sa.String(), nullable=True)
    op.create_check_constraint(
        "ck_applications_submitted_applicant_info",
        "applications",
        "is_draft OR (applicant_student_id IS NOT NULL AND btrim(applicant_student_id) <> '' "
        "AND applicant_name IS NOT NULL AND btrim(applicant_name) <> '' "
        "AND applicant_department IS NOT NULL AND btrim(applicant_department) <> '' "
        "AND applicant_phone IS NOT NULL AND btrim(applicant_phone) <> '' "
        "AND applicant_grade IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_applications_submitted_applicant_info", "applications", type_="check")
    op.execute("DELETE FROM applications WHERE is_draft AND (applicant_name IS NULL OR applicant_grade IS NULL)")
    for column in COLUMNS:
        op.alter_column("applications", column, existing_type=sa.String(), nullable=False)
