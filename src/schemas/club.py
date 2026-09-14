import re
from urllib.parse import urlparse
from email_validator import validate_email, EmailNotValidError
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal, Optional, List
from datetime import date


class ClubTagCreate(BaseModel):
    tag_key: str = Field(..., max_length=50)
    tag_value: str = Field(..., max_length=100)


class ClubTagResponse(BaseModel):
    tag_key: str
    tag_value: str

    model_config = {"from_attributes": True}


class ClubContactLink(BaseModel):
    type: Literal["email", "phone", "url"]
    label: str = Field(..., min_length=1, max_length=50)
    value: str = Field(..., min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_value_for_type(self):
        self.label = self.label.strip()
        self.value = self.value.strip()
        if self.type == "email":
            try:
                validate_email(self.value, check_deliverability=False)
            except EmailNotValidError as exc:
                raise ValueError("올바른 이메일 주소를 입력해주세요.") from exc
        elif self.type == "phone":
            if not re.fullmatch(r"[0-9+(). -]{7,20}", self.value):
                raise ValueError("올바른 전화번호를 입력해주세요.")
        else:
            parsed = urlparse(self.value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("링크는 http:// 또는 https:// 주소여야 합니다.")
        return self


class ClubActivityImageInput(BaseModel):
    image_url: str = Field(..., min_length=1, max_length=2048)
    caption: Optional[str] = Field(None, max_length=200)

    @model_validator(mode="after")
    def validate_and_clean(self):
        self.image_url = self.image_url.strip()
        parsed = urlparse(self.image_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("이미지 주소는 유효한 https:// 주소여야 합니다.")
        if self.caption is not None:
            self.caption = self.caption.strip() or None
        return self


class ClubActivityImageResponse(BaseModel):
    image_url: str
    caption: Optional[str] = None
    order_index: int

    model_config = {"from_attributes": True}


class ClubCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    club_type: Optional[Literal["department", "central"]] = None
    tagline: Optional[str] = Field(None, max_length=2_000)
    description: Optional[str] = Field(None, max_length=20_000)
    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=20)
    open_chat_url: Optional[str] = Field(None, max_length=2048)
    contact_links: List[ClubContactLink] = Field(default_factory=list, max_length=10)
    image_url: Optional[str] = Field(None, max_length=2048)
    activity_images: List[str] = Field(default_factory=list, max_length=20)
    activity_image_details: Optional[List[ClubActivityImageInput]] = Field(None, max_length=20)
    division: Optional[str] = Field(None, max_length=100)
    field: Optional[str] = Field(None, max_length=100)
    atmosphere: Optional[str] = Field(None, max_length=100)
    activity_purpose: Optional[str] = Field(None, max_length=100)
    activity_period: Optional[str] = Field(None, max_length=100)
    recruit_start: Optional[date] = None
    recruit_end: Optional[date] = None
    is_recruiting: bool = False
    tags: List[ClubTagCreate] = Field(default_factory=list, max_length=30)

    @field_validator("image_url", "activity_images")
    @classmethod
    def validate_image_urls(cls, value):
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is None:
                continue
            parsed = urlparse(str(item).strip())
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("이미지 주소는 유효한 https:// 주소여야 합니다.")
        return value

    @field_validator("activity_images")
    @classmethod
    def validate_unique_activity_images(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("중복된 활동 사진 주소를 사용할 수 없습니다.")
        return value

    @field_validator("activity_image_details")
    @classmethod
    def validate_unique_activity_image_details(cls, value):
        if value is not None:
            urls = [item.image_url for item in value]
            if len(urls) != len(set(urls)):
                raise ValueError("중복된 활동 사진 주소를 사용할 수 없습니다.")
        return value


class ClubUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    club_type: Optional[Literal["department", "central"]] = None
    tagline: Optional[str] = Field(None, max_length=2_000)
    description: Optional[str] = Field(None, max_length=20_000)
    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=20)
    open_chat_url: Optional[str] = Field(None, max_length=2048)
    contact_links: Optional[List[ClubContactLink]] = Field(None, max_length=10)
    image_url: Optional[str] = Field(None, max_length=2048)
    activity_images: Optional[List[str]] = Field(None, max_length=20)
    activity_image_details: Optional[List[ClubActivityImageInput]] = Field(None, max_length=20)
    division: Optional[str] = Field(None, max_length=100)
    field: Optional[str] = Field(None, max_length=100)
    atmosphere: Optional[str] = Field(None, max_length=100)
    activity_purpose: Optional[str] = Field(None, max_length=100)
    activity_period: Optional[str] = Field(None, max_length=100)
    recruit_start: Optional[date] = None
    recruit_end: Optional[date] = None
    is_recruiting: Optional[bool] = None
    tags: Optional[List[ClubTagCreate]] = Field(None, max_length=30)

    @field_validator("image_url", "activity_images")
    @classmethod
    def validate_image_urls(cls, value):
        return ClubCreate.validate_image_urls(value)

    @field_validator("activity_images")
    @classmethod
    def validate_unique_activity_images(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("중복된 활동 사진 주소를 사용할 수 없습니다.")
        return value

    @field_validator("activity_image_details")
    @classmethod
    def validate_unique_activity_image_details(cls, value):
        if value is not None:
            urls = [item.image_url for item in value]
            if len(urls) != len(set(urls)):
                raise ValueError("중복된 활동 사진 주소를 사용할 수 없습니다.")
        return value


class ClubResponse(BaseModel):
    id: str
    name: str
    club_type: Optional[str]
    tagline: Optional[str]
    description: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    open_chat_url: Optional[str]
    contact_links: List[ClubContactLink] = Field(default_factory=list)
    image_url: Optional[str]
    activity_images: List[str] = Field(default_factory=list)
    activity_image_details: List[ClubActivityImageResponse] = Field(default_factory=list)
    division: Optional[str]
    field: Optional[str]
    atmosphere: Optional[str]
    activity_purpose: Optional[str]
    activity_period: Optional[str]
    recruit_start: Optional[date]
    recruit_end: Optional[date]
    is_recruiting: bool
    member_count: int = 0
    tags: List[ClubTagResponse] = Field(default_factory=list)

    @field_validator("activity_images", mode="before")
    @classmethod
    def coerce_activity_images(cls, v):
        return v if isinstance(v, list) else []

    model_config = {"from_attributes": True}


class FormQuestionResponse(BaseModel):
    id: str
    question_text: str
    question_type: str
    is_required: bool
    order_index: int
    options: Optional[list] = None

    model_config = {"from_attributes": True}


class ApplicationFormResponse(BaseModel):
    id: str
    club_id: str
    title: str
    is_active: bool
    questions: List[FormQuestionResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class FormCreate(BaseModel):
    title: str = Field(..., max_length=200)


class FormUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None


class QuestionCreate(BaseModel):
    question_text: str = Field(..., min_length=1, max_length=2_000)
    question_type: Literal["text", "textarea", "choice", "multiselect"] = "text"
    is_required: bool = True
    order_index: int = Field(0, ge=0, le=1_000)
    options: Optional[List[str]] = Field(None, max_length=100)

    @model_validator(mode="after")
    def validate_options(self):
        if self.question_type in {"choice", "multiselect"}:
            if not self.options or len(self.options) < 2:
                raise ValueError("선택형 질문에는 두 개 이상의 선택지가 필요합니다.")
            cleaned = [option.strip() for option in self.options]
            if any(not option or len(option) > 200 for option in cleaned):
                raise ValueError("선택지는 1자 이상 200자 이하여야 합니다.")
            if len(cleaned) != len(set(cleaned)):
                raise ValueError("중복된 선택지를 사용할 수 없습니다.")
            self.options = cleaned
        elif self.options:
            raise ValueError("단답형과 장문형 질문에는 선택지를 설정할 수 없습니다.")
        return self


class QuestionUpdate(BaseModel):
    question_text: Optional[str] = Field(None, min_length=1, max_length=2_000)
    question_type: Optional[Literal["text", "textarea", "choice", "multiselect"]] = None
    is_required: Optional[bool] = None
    order_index: Optional[int] = Field(None, ge=0, le=1_000)
    options: Optional[List[str]] = Field(None, max_length=100)

    @field_validator("options")
    @classmethod
    def validate_option_items(cls, value):
        if value is None:
            return value
        cleaned = [option.strip() for option in value]
        if any(not option or len(option) > 200 for option in cleaned):
            raise ValueError("선택지는 1자 이상 200자 이하여야 합니다.")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("중복된 선택지를 사용할 수 없습니다.")
        return cleaned


class QuestionReorderRequest(BaseModel):
    question_ids: List[str] = Field(..., max_length=100)
