from __future__ import annotations
from uuid import uuid4
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin


class Club(TimestampMixin, Base):
    __tablename__ = "clubs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # 회원을 제외하고 기존 동아리만 이관할 수 있도록 초기에는 미지정일 수 있다.
    # 실제 관리자 권한은 active president membership으로만 판정한다.
    president_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    # 'department': 학과 동아리 / 'central': 중앙 동아리
    club_type: Mapped[str | None] = mapped_column(String(20))
    tagline: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    open_chat_url: Mapped[str | None] = mapped_column(Text)
    contact_links: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    image_url: Mapped[str | None] = mapped_column(String(255))
    activity_images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    division: Mapped[str | None] = mapped_column(String(100))
    field: Mapped[str | None] = mapped_column(String(100))
    atmosphere: Mapped[str | None] = mapped_column(String(100))
    activity_purpose: Mapped[str | None] = mapped_column(String(100))
    activity_period: Mapped[str | None] = mapped_column(String(100))
    recruit_start: Mapped[str | None] = mapped_column(Date)
    recruit_end: Mapped[str | None] = mapped_column(Date)
    is_recruiting: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tags = relationship("ClubTag", back_populates="club", cascade="all, delete-orphan")
    members = relationship("ClubMember", back_populates="club")
    application_forms = relationship("ApplicationForm", back_populates="club")
    posts = relationship("Post", back_populates="club")
    activity_image_records = relationship(
        "ClubActivityImage",
        back_populates="club",
        cascade="all, delete-orphan",
        order_by="ClubActivityImage.order_index",
    )

    @property
    def activity_image_details(self) -> list[dict]:
        """사진 설명을 제공하되 기존 activity_images 응답은 그대로 유지한다."""
        return [
            {
                "image_url": image.image_url,
                "caption": image.caption,
                "order_index": image.order_index,
            }
            for image in self.activity_image_records
        ]


class ClubActivityImage(TimestampMixin, Base):
    __tablename__ = "club_activity_images"
    __table_args__ = (
        CheckConstraint("order_index >= 0", name="ck_club_activity_images_order"),
        UniqueConstraint("club_id", "order_index", name="uq_club_activity_images_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    club = relationship("Club", back_populates="activity_image_records")


class ClubTag(Base):
    __tablename__ = "club_tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    club_id: Mapped[str] = mapped_column(String(36), ForeignKey("clubs.id"), nullable=False)
    tag_key: Mapped[str] = mapped_column(String(50), nullable=False)
    tag_value: Mapped[str] = mapped_column(String(100), nullable=False)

    club = relationship("Club", back_populates="tags")
