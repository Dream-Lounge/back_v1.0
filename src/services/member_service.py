from datetime import datetime
from sqlalchemy.orm import Session, selectinload

from src.models.club_member import ClubMember


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


def withdraw_member(db: Session, club_id: str, target_user_id: str) -> None:
    member = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == target_user_id,
        ClubMember.status == "active",
    ).first()
    if not member:
        raise LookupError("해당 부원을 찾을 수 없습니다.")
    if member.role == "president":
        raise ValueError("회장은 탈퇴 처리할 수 없습니다. 권한 이전 후 탈퇴해주세요.")

    member.status = "withdrawn"
    member.left_at = datetime.utcnow()
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
