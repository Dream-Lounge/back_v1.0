from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.dependencies import (
    get_current_user,
    get_optional_current_user,
    get_platform_roles,
    require_platform_editor,
)
from src.db.session import get_db
from src.schemas.post import (
    CommentCreate,
    CommentResponse,
    CommentUpdate,
    ContentReportCreate,
    ContentReportResponse,
    PostCreate,
    PostDetailResponse,
    PostListItem,
    PostUpdate,
)
from src.services import board_service
from src.utils.pagination import Page

router = APIRouter(prefix="/boards", tags=["boards"])


def _is_editor(db: Session, user_id: str) -> bool:
    return bool(get_platform_roles(db, user_id).intersection(
        {"union_admin", "developer", "super_admin"}
    ))


@router.get("/service/posts", response_model=Page[PostListItem])
def list_service_posts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
):
    return board_service.list_posts(db, "service", page, size, search)


@router.get("/service/posts/{post_id}", response_model=PostDetailResponse)
def get_service_post(post_id: str, db: Session = Depends(get_db)):
    post = board_service.get_post(db, "service", post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="게시글을 찾을 수 없습니다.")
    return post


@router.post("/service/posts", response_model=PostDetailResponse, status_code=status.HTTP_201_CREATED)
def create_service_post(
    body: PostCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_editor),
):
    try:
        return board_service.create_post(db, "service", current_user, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.patch("/service/posts/{post_id}", response_model=PostDetailResponse)
def update_service_post(
    post_id: str,
    body: PostUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_editor),
):
    try:
        return board_service.update_post(db, "service", post_id, current_user, body, True)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/service/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_editor),
):
    try:
        board_service.delete_post(db, "service", post_id, current_user, True)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/global/posts", response_model=Page[PostListItem])
def list_global_posts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
):
    return board_service.list_posts(db, "global", page, size, search)


@router.post("/global/posts", response_model=PostDetailResponse, status_code=status.HTTP_201_CREATED)
def create_global_post(
    body: PostCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return board_service.create_post(db, "global", current_user, body)


@router.get("/global/posts/{post_id}", response_model=PostDetailResponse)
def get_global_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_optional_current_user),
):
    post = board_service.get_post(
        db,
        "global",
        post_id,
        current_user.id if current_user else None,
        _is_editor(db, current_user.id) if current_user else False,
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="게시글을 찾을 수 없습니다.")
    return post


@router.patch("/global/posts/{post_id}", response_model=PostDetailResponse)
def update_global_post(
    post_id: str,
    body: PostUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        return board_service.update_post(
            db, "global", post_id, current_user, body,
            _is_editor(db, current_user.id),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.delete("/global/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_global_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        board_service.delete_post(
            db, "global", post_id, current_user, _is_editor(db, current_user.id)
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/global/posts/{post_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_global_comment(
    post_id: str,
    body: CommentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        return board_service.create_comment(db, "global", post_id, current_user, body.content)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch(
    "/global/posts/{post_id}/comments/{comment_id}", response_model=CommentResponse
)
def update_global_comment(
    post_id: str,
    comment_id: str,
    body: CommentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        return board_service.update_comment(
            db, post_id, comment_id, current_user, body.content,
            _is_editor(db, current_user.id),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.delete(
    "/global/posts/{post_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_global_comment(
    post_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        board_service.delete_comment(
            db, post_id, comment_id, current_user, _is_editor(db, current_user.id)
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/reports", response_model=ContentReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
    body: ContentReportCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        return board_service.create_report(
            db, current_user.id, body.post_id, body.comment_id, body.reason
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/reports", response_model=Page[ContentReportResponse])
def list_reports(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    report_status: Literal["open", "reviewed", "dismissed"] | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_editor),
):
    return board_service.list_reports(db, page, size, report_status)


@router.patch("/reports/{report_id}", response_model=ContentReportResponse)
def resolve_report(
    report_id: str,
    report_status: Literal["reviewed", "dismissed"] = Query(..., alias="status"),
    db: Session = Depends(get_db),
    current_user=Depends(require_platform_editor),
):
    try:
        return board_service.resolve_report(db, report_id, current_user.id, report_status)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
