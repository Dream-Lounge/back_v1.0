from sqlalchemy.orm import Session

from src.models.user import AuditLog


def queue_audit_log(
    db: Session,
    *,
    action: str,
    target_type: str,
    actor_user_id: str | None = None,
    target_id: str | None = None,
    payload: dict | None = None,
) -> AuditLog:
    """감사 행을 현재 트랜잭션에 추가한다. 호출자가 업무 변경과 함께 커밋한다."""
    log = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
    )
    db.add(log)
    return log
