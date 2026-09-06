from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.core.dependencies import require_club_member, require_club_president
from src.schemas.post import (
    PostCreate, PostUpdate, PostListItem, PostResponse, PostDetailResponse,
    CommentCreate, CommentResponse,
)
from src.services import post_service, notification_service
from src.services import club_service

router = APIRouter(prefix="/clubs", tags=["posts"])


@router.get("/{club_id}/posts", response_model=list[PostListItem])
def list_posts(
    club_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_member),
):
    """게시글 목록 (활동 중인 부원 전용). 공지가 상단에 표시됩니다."""
    return post_service.get_posts(db, club_id)


@router.post("/{club_id}/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
def create_post(
    club_id: str,
    body: PostCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_member),
):
    """게시글 작성. 회장이 작성하면 자동으로 공지 처리됩니다."""
    post = post_service.create_post(db, club_id, current_user, body)

    if post.is_notice:
        club = club_service.get_club(db, club_id)
        notification_service.send_notice_to_members(db, club_id, club.name, post.title, post.id)

    return post


@router.get("/{club_id}/posts/{post_id}", response_model=PostDetailResponse)
def get_post(
    club_id: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_member),
):
    """게시글 상세 + 댓글 목록 조회 (활동 중인 부원 전용)."""
    post = post_service.get_post(db, club_id, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="게시글을 찾을 수 없습니다.")
    return post


@router.patch("/{club_id}/posts/{post_id}", response_model=PostResponse)
def update_post(
    club_id: str,
    post_id: str,
    body: PostUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_member),
):
    """게시글 수정 (작성자 본인만)."""
    try:
        return post_service.update_post(db, club_id, post_id, current_user, body)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete("/{club_id}/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    club_id: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_member),
):
    """게시글 삭제 (작성자 본인 또는 회장)."""
    try:
        post_service.delete_post(db, club_id, post_id, current_user)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.patch("/{club_id}/posts/{post_id}/notice", response_model=PostResponse)
def toggle_notice(
    club_id: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_president),
):
    """공지 상태 전환 (회장 전용). 일반 글 → 공지 또는 공지 → 일반 글."""
    try:
        post = post_service.toggle_notice(db, club_id, post_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    if post.is_notice:
        club = club_service.get_club(db, club_id)
        notification_service.send_notice_to_members(db, club_id, club.name, post.title, post.id)

    return post


@router.post("/{club_id}/posts/{post_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def create_comment(
    club_id: str,
    post_id: str,
    body: CommentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_member),
):
    """댓글 작성 (부원 이상)."""
    post = post_service.get_post(db, club_id, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="게시글을 찾을 수 없습니다.")
    return post_service.create_comment(db, post_id, current_user, body.content)


@router.delete("/{club_id}/posts/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    club_id: str,
    post_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_member),
):
    """댓글 삭제 (작성자 본인 또는 회장)."""
    try:
        post_service.delete_comment(db, club_id, post_id, comment_id, current_user)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
