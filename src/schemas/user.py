from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class PrivacyConsentCreate(BaseModel):
    required_agreed: bool
    optional_agreed: bool = False
    policy_version: str = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def require_mandatory_consent(self):
        if not self.required_agreed:
            raise ValueError("필수 개인정보 수집 및 이용에 동의해야 합니다.")
        return self


class UserCreate(BaseModel):
    """학번, 이름, 실제 이메일과 안전한 비밀번호를 받는다."""

    student_id: str = Field(..., pattern=r"^\d{10}$")
    name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    phone: str = Field(..., min_length=9, max_length=20, pattern=r"^[0-9+(). -]+$")
    department: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    privacy_consent: PrivacyConsentCreate

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
        email = str(value).strip().lower()
        from src.core.config import settings

        domain = email.rsplit("@", 1)[-1]
        if domain not in settings.get_student_email_domains():
            raise ValueError("청주대학교 학생 이메일만 사용할 수 있습니다.")
        return email

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        phone = value.strip()
        digits = "".join(char for char in phone if char.isdigit())
        if not 9 <= len(digits) <= 15:
            raise ValueError("올바른 전화번호를 입력해주세요.")
        return phone

    @field_validator("department")
    @classmethod
    def normalize_department(cls, value: str) -> str:
        department = value.strip()
        if not department:
            raise ValueError("학과를 입력해주세요.")
        return department

    model_config = {"extra": "forbid"}


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


class EmailChangeRequest(BaseModel):
    new_email: EmailStr

    @field_validator("new_email")
    @classmethod
    def validate_student_email(cls, value: EmailStr) -> str:
        return UserCreate.normalize_email(value)


class EmailChangeVerificationRequest(BaseModel):
    new_email: EmailStr
    token: str = Field(..., min_length=6, max_length=64)

    @field_validator("new_email")
    @classmethod
    def validate_student_email(cls, value: EmailStr) -> str:
        return UserCreate.normalize_email(value)


class MessageResponse(BaseModel):
    message: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return UserCreate.validate_password(value)


class LoginRequest(BaseModel):
    student_id: str = Field(..., min_length=5, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(..., min_length=1, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(None, min_length=1)


class UserInfo(BaseModel):
    id: str
    student_id: str
    name: str
    phone: str | None
    department: str | None
    email: str
    email_verified: bool
    onboarding_completed: bool = False
    guide_seen: bool = False
    is_club_admin: bool = False
    platform_roles: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    token_type: str = "cookie"
    user: UserInfo


class UserResponse(BaseModel):
    id: str
    student_id: str
    name: str
    phone: str | None
    department: str | None
    email: str
    email_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    phone: str | None = Field(None, min_length=9, max_length=20, pattern=r"^[0-9+(). -]+$")
    department: str | None = Field(None, max_length=100)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("전화번호는 비워둘 수 없습니다.")
        return UserCreate.normalize_phone(value)

    @field_validator("department")
    @classmethod
    def normalize_department(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    model_config = {"extra": "forbid"}


class UserInterestInput(BaseModel):
    tag_key: str = Field(..., min_length=1, max_length=50)
    tag_value: str = Field(..., min_length=1, max_length=100)

    @model_validator(mode="after")
    def strip_values(self):
        self.tag_key = self.tag_key.strip()
        self.tag_value = self.tag_value.strip()
        if not self.tag_key or not self.tag_value:
            raise ValueError("관심분야 분류와 값을 입력해주세요.")
        return self

    model_config = {"from_attributes": True}


class UserInterestsUpdate(BaseModel):
    interests: list[UserInterestInput] = Field(..., max_length=30)
    complete_onboarding: bool = True

    @field_validator("interests")
    @classmethod
    def reject_duplicates(cls, value: list[UserInterestInput]):
        keys = [(item.tag_key, item.tag_value) for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("같은 관심분야를 중복해서 저장할 수 없습니다.")
        return value


class UserInterestsResponse(BaseModel):
    interests: list[UserInterestInput]
    onboarding_completed: bool
