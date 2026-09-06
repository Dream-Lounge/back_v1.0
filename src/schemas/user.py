from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class EmailVerifySendRequest(BaseModel):
    email: EmailStr


class EmailVerifyConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class EmailVerifyConfirmResponse(BaseModel):
    message: str
    verification_token: str


class PrivacyConsentCreate(BaseModel):
    required_agreed: bool
    optional_agreed: bool = False


class UserCreate(BaseModel):
    """가두모집용 간편 계정: 프런트와 동일하게 학번과 PIN만 받는다."""

    student_id: str = Field(..., pattern=r"^\d{10}$")
    password: str = Field(..., pattern=r"^\d{4}$")


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
    email: str
    phone: Optional[str]
    department: Optional[str]

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserInfo


class UserResponse(BaseModel):
    id: str
    student_id: str
    name: str
    email: str
    phone: Optional[str]
    department: Optional[str]
    email_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}
