from pydantic import BaseModel, Field
from typing import Optional, List
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
    answers: List[ApplicationAnswerCreate] = Field(default_factory=list, max_length=100)
    applicant_student_id: Optional[str] = Field(None, max_length=20)
    applicant_name: Optional[str] = Field(None, max_length=50)
    applicant_department: Optional[str] = Field(None, max_length=100)
    applicant_phone: Optional[str] = Field(None, max_length=20)
    applicant_grade: Optional[str] = Field(None, pattern=r"^(?:[1-6])?$")


class ApplicationUpdate(BaseModel):
    is_draft: Optional[bool] = None
    answers: Optional[List[ApplicationAnswerCreate]] = None
    applicant_student_id: Optional[str] = Field(None, max_length=20)
    applicant_name: Optional[str] = Field(None, max_length=50)
    applicant_department: Optional[str] = Field(None, max_length=100)
    applicant_phone: Optional[str] = Field(None, max_length=20)
    applicant_grade: Optional[str] = Field(None, pattern=r"^(?:[1-6])?$")


class ApplicationAnswerResponse(BaseModel):
    question_id: str
    answer_text: Optional[str]

    model_config = {"from_attributes": True}


class ApplicationResponse(BaseModel):
    id: str
    form_id: str
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    status: str
    is_draft: bool
    submitted_at: Optional[datetime]
    updated_at: datetime
    admin_comment: Optional[str] = None
    applicant_student_id: Optional[str] = None
    applicant_name: Optional[str] = None
    applicant_department: Optional[str] = None
    applicant_phone: Optional[str] = None
    applicant_grade: Optional[str] = None
    answers: List[ApplicationAnswerResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ApplicationListItem(BaseModel):
    id: str
    form_id: str
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    status: str
    is_draft: bool
    submitted_at: Optional[datetime]
    updated_at: datetime
    admin_comment: Optional[str] = None

    model_config = {"from_attributes": True}


class ActiveClubItem(BaseModel):
    club_id: str
    club_name: str
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}


class AdminApplicationListItem(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_student_id: str
    user_department: Optional[str]
    status: str
    submitted_at: Optional[datetime]
    admin_comment: Optional[str] = None
    applicant_department: Optional[str] = None
    applicant_phone: Optional[str] = None
    applicant_grade: Optional[str] = None

    model_config = {"from_attributes": True}


class AdminApplicationResponse(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_student_id: str
    user_department: Optional[str]
    status: str
    submitted_at: Optional[datetime]
    admin_comment: Optional[str] = None
    applicant_department: Optional[str] = None
    applicant_phone: Optional[str] = None
    applicant_grade: Optional[str] = None
    answers: List[ApplicationAnswerResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
