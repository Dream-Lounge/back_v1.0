from sqlalchemy.orm import Session, selectinload

from src.models.club_member import ClubMember
from src.utils.time import utc_now_naive


def list_members(db: Session, club_id: str, page: int = 1, size: int = 20) -> dict:
    query = (
        db.query(ClubMember)
        .options(selectinload(ClubMember.user))
        .filter(ClubMember.club_id == club_id, ClubMember.status == "active")
    )
    total = query.count()
    members = (
        query.order_by(ClubMember.joined_at.asc(), ClubMember.id.asc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    items = [
        {
            "user_id": m.user_id,
            "name": m.user.name,
            "student_id": m.user.student_id,
            "department": m.user.department,
            "phone": m.user.phone,
            "role": m.role,
            "joined_at": m.joined_at,
        }
        for m in members
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


def get_member(db: Session, club_id: str, user_id: str) -> dict:
    membership = (
        db.query(ClubMember)
        .options(selectinload(ClubMember.user))
        .filter(
            ClubMember.club_id == club_id,
            ClubMember.user_id == user_id,
            ClubMember.status == "active",
        )
        .first()
    )
    if not membership:
        raise LookupError("대상 부원을 찾을 수 없습니다.")
    return {
        "user_id": membership.user_id,
        "name": membership.user.name,
        "student_id": membership.user.student_id,
        "department": membership.user.department,
        "phone": membership.user.phone,
        "role": membership.role,
        "joined_at": membership.joined_at,
    }


def withdraw_member(db: Session, club_id: str, target_user_id: str) -> None:
    member = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == target_user_id,
        ClubMember.status == "active",
    ).first()
    if not member:
        raise LookupError("해당 부원을 찾을 수 없습니다.")
    if member.role in {"president", "admin"}:
        raise ValueError("회장 또는 관리자는 역할을 해제한 후 탈퇴 처리해주세요.")

    member.status = "withdrawn"
    member.left_at = utc_now_naive()
    db.commit()


def transfer_role(db: Session, club_id: str, current_president_id: str, target_user_id: str) -> None:
    if current_president_id == target_user_id:
        raise ValueError("본인에게 권한을 이전할 수 없습니다.")

    new_president = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == target_user_id,
        ClubMember.status == "active",
    ).first()
    if not new_president:
        raise LookupError("대상 부원을 찾을 수 없습니다.")

    old_president = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == current_president_id,
        ClubMember.role == "president",
    ).first()

    old_president.role = "member"
    new_president.role = "president"

    from src.models.club import Club
    db.query(Club).filter(Club.id == club_id).update({"president_id": target_user_id})

    db.commit()


def assign_admin(db: Session, club_id: str, target_user_id: str) -> ClubMember:
    """회장이 활성 부원을 동일 동아리의 관리자로 승격한다."""
    membership = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == target_user_id,
        ClubMember.status == "active",
    ).with_for_update().first()
    if not membership:
        raise LookupError("대상 부원을 찾을 수 없습니다.")
    if membership.role == "president":
        raise ValueError("동아리 회장은 관리자 역할로 변경할 수 없습니다.")
    if membership.role == "admin":
        return membership

    membership.role = "admin"
    db.commit()
    db.refresh(membership)
    return membership


def revoke_admin(db: Session, club_id: str, target_user_id: str) -> ClubMember:
    """회장이 동아리 관리자를 일반 동아리 회원으로 변경한다."""
    membership = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == target_user_id,
        ClubMember.status == "active",
    ).with_for_update().first()
    if not membership:
        raise LookupError("대상 부원을 찾을 수 없습니다.")
    if membership.role == "president":
        raise ValueError("동아리 회장의 권한은 관리자 해제로 변경할 수 없습니다.")
    if membership.role != "admin":
        raise ValueError("해당 부원은 동아리 관리자가 아닙니다.")

    membership.role = "member"
    db.commit()
    db.refresh(membership)
    return membership
