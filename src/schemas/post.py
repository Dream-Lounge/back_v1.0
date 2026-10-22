from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=50_000)
    is_anonymous: bool = False


class PostUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = Field(None, min_length=1, max_length=50_000)


class PostListItem(BaseModel):
    id: str
    author_id: str | None
    author_name: str = ""
    post_type: str
    title: str
    is_notice: bool
    board_scope: str = "club"
    is_anonymous: bool = False
    created_at: datetime
    comment_count: int = 0
    is_author_president: bool = False

    model_config = {"from_attributes": True}


class PostResponse(BaseModel):
    id: str
    club_id: str | None
    author_id: str | None
    post_type: str
    title: str
    content: str
    is_notice: bool
    board_scope: str = "club"
    is_anonymous: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5_000)


class CommentUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5_000)


class CommentResponse(BaseModel):
    id: str
    post_id: str
    author_id: str
    author_name: str = ""
    content: str
    created_at: datetime
    is_author_president: bool = False

    model_config = {"from_attributes": True}


class PostDetailResponse(BaseModel):
    id: str
    club_id: str | None
    author_id: str | None
    author_name: str = ""
    post_type: str
    title: str
    content: str
    is_notice: bool
    board_scope: str = "club"
    is_anonymous: bool = False
    created_at: datetime
    is_author_president: bool = False
    comments: list[CommentResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ContentReportCreate(BaseModel):
    post_id: str | None = None
    comment_id: str | None = None
    reason: str = Field(..., min_length=1, max_length=500)

    @classmethod
    def _target_count(cls, post_id, comment_id):
        return int(post_id is not None) + int(comment_id is not None)

    @model_validator(mode="after")
    def validate_target(self):
        if self._target_count(self.post_id, self.comment_id) != 1:
            raise ValueError("게시글 또는 댓글 중 하나만 신고할 수 있습니다.")
        return self


class ContentReportResponse(BaseModel):
    id: str
    reporter_id: str
    post_id: str | None
    comment_id: str | None
    reason: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
