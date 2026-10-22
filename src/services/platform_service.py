from sqlalchemy.orm import Session

from src.models.user import PlatformRole, User
from src.services.audit_service import queue_audit_log
from src.utils.time import utc_now_naive


def list_roles(db: Session) -> list[PlatformRole]:
    return db.query(PlatformRole).order_by(
        PlatformRole.revoked_at.is_not(None), PlatformRole.granted_at.desc()
    ).all()


def grant_role(
    db: Session, actor_user_id: str, user_id: str, role: str
) -> PlatformRole:
    if not db.get(User, user_id):
        raise LookupError("사용자를 찾을 수 없습니다.")
    existing = db.query(PlatformRole).filter(
        PlatformRole.user_id == user_id,
        PlatformRole.role == role,
        PlatformRole.revoked_at.is_(None),
    ).with_for_update().first()
    if existing:
        return existing
    record = PlatformRole(
        user_id=user_id, role=role, granted_by=actor_user_id
    )
    db.add(record)
    db.flush()
    queue_audit_log(
        db,
        actor_user_id=actor_user_id,
        action="platform.role_granted",
        target_type="platform_role",
        target_id=record.id,
        payload={"user_id": user_id, "role": role},
    )
    db.commit()
    db.refresh(record)
    return record


def revoke_role(db: Session, actor_user_id: str, role_id: str) -> PlatformRole:
    record = db.query(PlatformRole).filter(
        PlatformRole.id == role_id,
        PlatformRole.revoked_at.is_(None),
    ).with_for_update().first()
    if not record:
        raise LookupError("활성 운영자 권한을 찾을 수 없습니다.")
    if record.user_id == actor_user_id and record.role == "super_admin":
        raise ValueError("자신의 최고 관리자 권한은 직접 해제할 수 없습니다.")
    record.revoked_at = utc_now_naive()
    queue_audit_log(
        db,
        actor_user_id=actor_user_id,
        action="platform.role_revoked",
        target_type="platform_role",
        target_id=record.id,
        payload={"user_id": record.user_id, "role": record.role},
    )
    db.commit()
    db.refresh(record)
    return record
