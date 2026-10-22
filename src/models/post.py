from __future__ import annotations
from uuid import uuid4
from sqlalchemy import String, Boolean, Text, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin


class Post(TimestampMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint("board_scope IN ('global', 'service', 'club')", name="ck_posts_board_scope"),
        CheckConstraint(
            "(board_scope = 'club' AND club_id IS NOT NULL) OR "
            "(board_scope IN ('global', 'service') AND club_id IS NULL)",
            name="ck_posts_scope_club",
        ),
        Index("ix_posts_scope_created", "board_scope", "is_deleted", "created_at"),
        Index("ix_posts_club_created", "club_id", "is_deleted", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    club_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("clubs.id"), nullable=True)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    board_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="club")
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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


class ContentReport(TimestampMixin, Base):
    __tablename__ = "content_reports"
    __table_args__ = (
        CheckConstraint(
            "(post_id IS NOT NULL AND comment_id IS NULL) OR "
            "(post_id IS NULL AND comment_id IS NOT NULL)",
            name="ck_content_reports_one_target",
        ),
        CheckConstraint(
            "status IN ('open', 'reviewed', 'dismissed')",
            name="ck_content_reports_status",
        ),
        Index("ix_content_reports_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    reporter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("posts.id", ondelete="CASCADE"), nullable=True
    )
    comment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
