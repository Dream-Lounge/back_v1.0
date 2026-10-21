from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from typing import Optional


class PrivacyConsentCreate(BaseModel):
    required_agreed: bool
    optional_agreed: bool = False


class UserCreate(BaseModel):
    """학번, 이름, 실제 이메일과 안전한 비밀번호를 받는다."""

    student_id: str = Field(..., pattern=r"^\d{10}$")
    name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("이름을 입력해주세요.")
        return name

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not any(not char.isalnum() and not char.isspace() for char in value):
            raise ValueError("비밀번호에는 특수문자를 1개 이상 포함해주세요.")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class EmailVerificationRequest(BaseModel):
    email: EmailStr
    token: str = Field(..., min_length=6, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class EmailResendRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class MessageResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    student_id: str = Field(..., min_length=5, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(..., min_length=1, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = Field(None, min_length=1)


class UserInfo(BaseModel):
    id: str
    student_id: str
    name: str
    phone: Optional[str]
    department: Optional[str]
    is_club_admin: bool = False

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    token_type: str = "cookie"
    user: UserInfo


class UserResponse(BaseModel):
    id: str
    student_id: str
    name: str
    phone: Optional[str]
    department: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
