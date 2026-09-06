from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.core.dependencies import require_club_president
from src.schemas.member import MemberResponse
from src.services import member_service
from src.utils.pagination import Page

router = APIRouter(prefix="/clubs", tags=["members"])


@router.get("/{club_id}/members", response_model=Page[MemberResponse])
def list_members(
    club_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(require_club_president),
):
    """동아리 회원 명단 조회 (회장 전용)."""
    return member_service.list_members(db, club_id, page, size)


@router.patch("/{club_id}/members/{user_id}/withdraw", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_member(
    club_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_president),
):
    """부원 탈퇴 처리 (회장 전용)."""
    try:
        member_service.withdraw_member(db, club_id, user_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{club_id}/members/{user_id}/role", status_code=status.HTTP_204_NO_CONTENT)
def transfer_role(
    club_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_president),
):
    """권한 이전 — 해당 부원이 회장이 되고 기존 회장은 일반 부원으로 변경됩니다 (회장 전용)."""
    try:
        member_service.transfer_role(db, club_id, current_user.id, user_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
