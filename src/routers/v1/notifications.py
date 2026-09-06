from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.core.dependencies import get_current_user
from src.schemas.notification import NotificationResponse
from src.services import notification_service

router = APIRouter(prefix="/me/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """내 알림 목록 (최신순)."""
    return notification_service.get_notifications(db, current_user.id)


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


@router.patch("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_as_read(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """모든 알림 읽음 처리."""
    notification_service.mark_all_as_read(db, current_user.id)
