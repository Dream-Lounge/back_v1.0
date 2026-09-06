from __future__ import annotations
from uuid import uuid4
from sqlalchemy import String, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin


class Post(TimestampMixin, Base):
    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    club_id: Mapped[str] = mapped_column(String(36), ForeignKey("clubs.id"), nullable=False)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # 'notice': 공지 / 'general': 일반 글
    post_type: Mapped[str] = mapped_column(String(20), nullable=False, default="general")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_notice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    club = relationship("Club", back_populates="posts")
    author = relationship("User", foreign_keys=[author_id])
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")

    @property
    def author_name(self) -> str:
        return self.author.name if self.author else ""


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    post_id: Mapped[str] = mapped_column(String(36), ForeignKey("posts.id"), nullable=False)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    post = relationship("Post", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id])

    @property
    def author_name(self) -> str:
        return self.author.name if self.author else ""
