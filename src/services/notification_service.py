from sqlalchemy.orm import Session
from src.models.notification import Notification
from src.models.club_member import ClubMember


def _create(db: Session, recipient_id: str, noti_type: str, message: str, payload: dict | None = None) -> Notification:
    n = Notification(recipient_id=recipient_id, noti_type=noti_type, message=message, payload=payload)
    db.add(n)
    return n


def send_application_result(db: Session, user_id: str, club_name: str, status: str) -> None:
    status_label = {"pending": "보류(1차합격)", "passed": "최종합격", "failed": "불합격"}[status]
    message = f"[{club_name}] 동아리 신청 결과: {status_label}"
    _create(db, user_id, "application_result", message, {"club_name": club_name, "status": status})
    db.commit()


def send_notice_to_members(db: Session, club_id: str, club_name: str, post_title: str, post_id: str) -> None:
    members = (
        db.query(ClubMember)
        .filter(ClubMember.club_id == club_id, ClubMember.status == "active")
        .all()
    )
    message = f"[{club_name}] 새 공지: {post_title}"
    for m in members:
        _create(db, m.user_id, "new_notice", message, {"club_id": club_id, "post_id": post_id})
    db.commit()


def get_notifications(db: Session, user_id: str) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.recipient_id == user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )


def mark_as_read(db: Session, user_id: str, notification_id: str) -> Notification:
    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.recipient_id == user_id,
    ).first()
    if not n:
        raise LookupError("알림을 찾을 수 없습니다.")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n


def mark_all_as_read(db: Session, user_id: str) -> None:
    db.query(Notification).filter(
        Notification.recipient_id == user_id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
