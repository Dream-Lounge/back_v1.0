from __future__ import annotations
from uuid import uuid4
from datetime import datetime
from sqlalchemy import String, Boolean, Text, Integer, DateTime, ForeignKey, JSON, UniqueConstraint, Index, CheckConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin
from src.utils.time import utc_now_naive


class ApplicationForm(TimestampMixin, Base):
    __tablename__ = "application_forms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    club_id: Mapped[str] = mapped_column(String(36), ForeignKey("clubs.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    club = relationship("Club", back_populates="application_forms")
    questions = relationship(
        "FormQuestion",
        back_populates="form",
        order_by="FormQuestion.order_index",
        cascade="all, delete-orphan",
    )
    applications = relationship("Application", back_populates="form")


class FormQuestion(Base):
    __tablename__ = "form_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    form_id: Mapped[str] = mapped_column(String(36), ForeignKey("application_forms.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 'text': 단답·서술 / 'choice': 단일 선택 / 'multiselect': 복수 선택
    question_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    options: Mapped[dict | None] = mapped_column(JSON)

    form = relationship("ApplicationForm", back_populates="questions")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("form_id", "user_id", name="uq_applications_form_user"),
        CheckConstraint(
            "(applicant_type = 'member' AND user_id IS NOT NULL) OR "
            "(applicant_type = 'guest' AND user_id IS NULL)",
            name="ck_applications_applicant_identity",
        ),
        CheckConstraint(
            "(linked_user_id IS NULL AND linked_at IS NULL) OR "
            "(linked_user_id IS NOT NULL AND linked_at IS NOT NULL)",
            name="ck_applications_link_pair",
        ),
        CheckConstraint(
            "(applicant_type = 'member' AND guest_notice_agreed_at IS NULL) OR "
            "(applicant_type = 'guest' AND guest_notice_agreed_at IS NOT NULL)",
            name="ck_applications_guest_notice_consent",
        ),
        Index(
            "uq_applications_guest_form_student_active",
            "form_id",
            "applicant_student_id",
            unique=True,
            postgresql_where=text("applicant_type = 'guest' AND deleted_at IS NULL"),
            sqlite_where=text("applicant_type = 'guest' AND deleted_at IS NULL"),
        ),
        Index(
            "ix_applications_admin_listing",
            "form_id",
            "applicant_type",
            "deleted_at",
            "status",
            "submitted_at",
        ),
        Index(
            "ix_applications_guest_link_lookup",
            "applicant_type",
            "status",
            "applicant_student_id",
            "applicant_email",
            "link_expires_at",
            postgresql_where=text("linked_user_id IS NULL AND deleted_at IS NULL"),
            sqlite_where=text("linked_user_id IS NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    form_id: Mapped[str] = mapped_column(String(36), ForeignKey("application_forms.id"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    applicant_type: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    # 'draft': 임시저장 / 'submitted': 제출 / 'pending': 보류(1차합격) /
    # 'passed': 최종합격 / 'failed': 불합격
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    applicant_student_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    applicant_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    applicant_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applicant_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    applicant_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    applicant_grade: Mapped[str | None] = mapped_column(String(1), nullable=True)
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    privacy_policy_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    privacy_agreed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    guest_notice_agreed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    linked_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 제출 시점의 폼/문항을 보존한다. 이후 관리자가 활성 폼을 수정해도
    # 이미 제출된 지원서의 질문과 선택지는 바뀌지 않는다.
    form_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    form = relationship("ApplicationForm", back_populates="applications")
    user = relationship("User", back_populates="applications", foreign_keys=[user_id])
    answers = relationship(
        "ApplicationAnswer",
        back_populates="application",
        cascade="all, delete-orphan",
    )


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    application_id: Mapped[str] = mapped_column(String(36), ForeignKey("applications.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(String(36), ForeignKey("form_questions.id"), nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)

    application = relationship("Application", back_populates="answers")
    question = relationship("FormQuestion")
