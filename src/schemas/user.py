from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class PrivacyConsentCreate(BaseModel):
    required_agreed: bool
    optional_agreed: bool = False


class UserCreate(BaseModel):
    """간소화 버전 계정: 학번과 숫자 4자리 PIN만 받는다."""

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
    phone: Optional[str]
    department: Optional[str]

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
