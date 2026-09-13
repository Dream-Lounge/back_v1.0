from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.utils.time import utc_now_naive


class ClubAdmin(Base):
    """운영자가 지정한 동아리 관리자 허용 목록.

    이 테이블의 행은 관리자 화면 접근 자격만 뜻한다. 실제 동아리 소유권은
    ``club_members.role == \"president\"``로 별도 확인한다.
    """

    __tablename__ = "club_admins"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )

    user = relationship("User", back_populates="club_admin_record")
