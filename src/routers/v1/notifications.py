from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.dependencies import get_current_user
from src.db.session import get_db
from src.schemas.notification import (
    NotificationResponse,
    UnreadNotificationCountResponse,
)
from src.services import notification_service
from src.utils.pagination import Page

router = APIRouter(prefix="/me/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """내 알림 목록 (최신순)."""
    return notification_service.get_notifications(db, current_user.id)


@router.get("/page", response_model=Page[NotificationResponse])
def list_notifications_page(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return notification_service.get_notifications_page(db, current_user.id, page, size)


@router.get("/unread-count", response_model=UnreadNotificationCountResponse)
def unread_count(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return {"count": notification_service.get_unread_count(db, current_user.id)}


@router.patch("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_as_read(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """모든 알림 읽음 처리."""
    notification_service.mark_all_as_read(db, current_user.id)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_as_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """알림 읽음 처리."""
    try:
        return notification_service.mark_as_read(db, current_user.id, notification_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
