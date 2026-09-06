from __future__ import annotations
from uuid import uuid4
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base


class ClubMember(Base):
    __tablename__ = "club_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    club_id: Mapped[str] = mapped_column(String(36), ForeignKey("clubs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # 'president': 동아리 회장 / 'member': 일반 부원
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    # 'active': 활동 중 / 'withdrawn': 탈퇴
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime)

    club = relationship("Club", back_populates="members")
    user = relationship("User", back_populates="club_memberships")
