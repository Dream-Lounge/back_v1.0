from __future__ import annotations
from uuid import uuid4
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base
from src.utils.time import utc_now_naive


class ClubMember(Base):
    __tablename__ = "club_members"
    __table_args__ = (
        Index(
            "uq_club_members_one_active_presidency_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active' AND role = 'president'"),
            sqlite_where=text("status = 'active' AND role = 'president'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    club_id: Mapped[str] = mapped_column(String(36), ForeignKey("clubs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # 'president': 동아리 회장 / 'member': 일반 부원
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    # 'active': 활동 중 / 'withdrawn': 탈퇴
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime)

    club = relationship("Club", back_populates="members")
    user = relationship("User", back_populates="club_memberships")
