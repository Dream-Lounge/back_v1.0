from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
import logging
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.core.security import decode_access_token

bearer = HTTPBearer()
logger = logging.getLogger(__name__)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError
        from src.models.user import User
        user = db.get(User, user_id)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 인증 토큰입니다.",
        )
    except Exception as exc:
        logger.error("인증 처리 중 DB 오류: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
        )
    return user


def require_club_president(club_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """해당 동아리의 현직 회장인지 확인. 아니면 403."""
    from src.models.club_member import ClubMember
    membership = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == current_user.id,
        ClubMember.role == "president",
        ClubMember.status == "active",
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="동아리 회장만 접근할 수 있습니다.",
        )
    return current_user


def require_club_member(club_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """해당 동아리의 active 부원(회장 포함)인지 확인. 아니면 403."""
    from src.models.club_member import ClubMember
    membership = db.query(ClubMember).filter(
        ClubMember.club_id == club_id,
        ClubMember.user_id == current_user.id,
        ClubMember.status == "active",
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="동아리 부원만 접근할 수 있습니다.",
        )
    return current_user
