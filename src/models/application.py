from __future__ import annotations
from uuid import uuid4
from datetime import datetime
from sqlalchemy import String, Boolean, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin


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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    form_id: Mapped[str] = mapped_column(String(36), ForeignKey("application_forms.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # 'draft': 임시저장 / 'submitted': 제출 / 'pending': 보류(1차합격) /
    # 'passed': 최종합격 / 'failed': 불합격
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    applicant_student_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    applicant_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    applicant_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applicant_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    applicant_grade: Mapped[str | None] = mapped_column(String(1), nullable=True)
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    form = relationship("ApplicationForm", back_populates="applications")
    user = relationship("User", back_populates="applications")
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
