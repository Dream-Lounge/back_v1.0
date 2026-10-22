from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Optional, List, Literal
from datetime import datetime


class ApplicationAnswerCreate(BaseModel):
    question_id: str = Field(..., min_length=36, max_length=36, pattern=r"^[0-9a-fA-F-]{36}$")
    answer_text: str = Field(..., max_length=10_000)


class ApplicationStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|passed|failed)$")


class ApplicationCommentUpdate(BaseModel):
    comment: str = Field(..., max_length=2000)


class ApplicationCreate(BaseModel):
    form_id: str
    is_draft: bool = True
    privacy_consent: bool = False
    answers: List[ApplicationAnswerCreate] = Field(default_factory=list, max_length=100)
    applicant_student_id: Optional[str] = Field(None, max_length=20)
    applicant_name: Optional[str] = Field(None, max_length=50)
    applicant_department: Optional[str] = Field(None, max_length=100)
    applicant_phone: Optional[str] = Field(None, max_length=20)
    applicant_grade: Optional[str] = Field(None, pattern=r"^(?:[1-6])?$")


class GuestApplicationCreate(BaseModel):
    form_id: str
    applicant_student_id: str = Field(..., pattern=r"^\d{10}$")
    applicant_name: str = Field(..., min_length=1, max_length=50)
    applicant_department: str = Field(..., min_length=1, max_length=100)
    applicant_phone: str = Field(..., min_length=9, max_length=20, pattern=r"^[0-9+(). -]+$")
    applicant_email: EmailStr
    applicant_grade: Optional[str] = Field(None, pattern=r"^(?:[1-6])?$")
    privacy_consent: bool
    guest_notice_consent: bool
    privacy_policy_version: str = Field(..., min_length=1, max_length=50)
    answers: List[ApplicationAnswerCreate] = Field(default_factory=list, max_length=100)

    @field_validator("applicant_name", "applicant_department")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("필수 신청자 정보를 입력해주세요.")
        return cleaned

    @field_validator("applicant_email")
    @classmethod
    def validate_student_email(cls, value: EmailStr) -> str:
        from src.core.config import settings

        email = str(value).strip().lower()
        if email.rsplit("@", 1)[-1] not in settings.get_student_email_domains():
            raise ValueError("청주대학교 학생 이메일만 사용할 수 있습니다.")
        return email

    @field_validator("applicant_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        cleaned = value.strip()
        if not 9 <= len("".join(char for char in cleaned if char.isdigit())) <= 15:
            raise ValueError("올바른 전화번호를 입력해주세요.")
        return cleaned

    @model_validator(mode="after")
    def require_privacy_consent(self):
        if not self.privacy_consent:
            raise ValueError("개인정보 수집 및 이용에 동의해주세요.")
        if not self.guest_notice_consent:
            raise ValueError(
                "비회원은 임시저장과 제출 결과 확인이 불가능하다는 안내에 동의해주세요."
            )
        return self


class GuestApplicationsLinkResponse(BaseModel):
    linked_application_ids: list[str]
    linked_club_ids: list[str]
    linked_count: int


class ApplicationAdminDeleteRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ApplicationUpdate(BaseModel):
    is_draft: Optional[bool] = None
    privacy_consent: bool = False
    answers: Optional[List[ApplicationAnswerCreate]] = None
    applicant_student_id: Optional[str] = Field(None, max_length=20)
    applicant_name: Optional[str] = Field(None, max_length=50)
    applicant_department: Optional[str] = Field(None, max_length=100)
    applicant_phone: Optional[str] = Field(None, max_length=20)
    applicant_grade: Optional[str] = Field(None, pattern=r"^(?:[1-6])?$")


class ApplicationAnswerResponse(BaseModel):
    question_id: str
    answer_text: Optional[str]
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    is_required: Optional[bool] = None
    order_index: Optional[int] = None
    options: Optional[List[str]] = None

    model_config = {"from_attributes": True}


class ApplicationResponse(BaseModel):
    id: str
    form_id: str
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    club_image: Optional[str] = None
    club_category: Optional[str] = None
    status: str
    is_draft: bool
    submitted_at: Optional[datetime]
    updated_at: datetime
    admin_comment: Optional[str] = None
    applicant_type: Literal["member", "guest"] = "member"
    applicant_student_id: Optional[str] = None
    applicant_name: Optional[str] = None
    applicant_department: Optional[str] = None
    applicant_phone: Optional[str] = None
    applicant_email: Optional[str] = None
    applicant_grade: Optional[str] = None
    answers: List[ApplicationAnswerResponse] = Field(default_factory=list)
    form_snapshot: Optional[dict] = None

    model_config = {"from_attributes": True}


class ApplicationListItem(BaseModel):
    id: str
    form_id: str
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    club_image: Optional[str] = None
    club_category: Optional[str] = None
    status: str
    is_draft: bool
    submitted_at: Optional[datetime]
    updated_at: datetime
    admin_comment: Optional[str] = None
    applicant_type: Literal["member", "guest"] = "member"

    model_config = {"from_attributes": True}


class ActiveClubItem(BaseModel):
    club_id: str
    club_name: str
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}


class AdminApplicationListItem(BaseModel):
    id: str
    user_id: Optional[str]
    user_name: str
    user_student_id: str
    user_department: Optional[str]
    status: str
    submitted_at: Optional[datetime]
    admin_comment: Optional[str] = None
    applicant_department: Optional[str] = None
    applicant_phone: Optional[str] = None
    applicant_email: Optional[str] = None
    applicant_grade: Optional[str] = None
    applicant_type: Literal["member", "guest"] = "member"

    model_config = {"from_attributes": True}


class AdminApplicationResponse(BaseModel):
    id: str
    user_id: Optional[str]
    user_name: str
    user_student_id: str
    user_department: Optional[str]
    status: str
    submitted_at: Optional[datetime]
    admin_comment: Optional[str] = None
    applicant_department: Optional[str] = None
    applicant_phone: Optional[str] = None
    applicant_email: Optional[str] = None
    applicant_grade: Optional[str] = None
    applicant_type: Literal["member", "guest"] = "member"
    answers: List[ApplicationAnswerResponse] = Field(default_factory=list)
    form_snapshot: Optional[dict] = None

    model_config = {"from_attributes": True}
