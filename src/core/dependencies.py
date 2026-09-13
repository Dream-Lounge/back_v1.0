from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
import logging
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.core.security import decode_access_token
from src.core.config import settings
from src.utils.supabase_jwt import decode_supabase_access_token

bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    from src.models.user import User

    access_token = (
        credentials.credentials
        if credentials is not None
        else request.cookies.get("dreamlounge_access")
    )
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다.",
        )

    try:
        payload = decode_access_token(access_token)
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError
        user = db.get(User, user_id)
    except (JWTError, ValueError):
        # 운영 Supabase access token은 ES256 공개키로 로컬 검증한다.
        # 잘못된 토큰을 Auth 서버로 전달하는 fallback을 두지 않아 원격
        # 검증 지연과 공격자가 유발할 수 있는 Auth 요청 증폭을 차단한다.
        try:
            payload = decode_supabase_access_token(access_token)
            user = db.query(User).filter(
                User.auth_user_id == payload["sub"]
            ).first()
        except (JWTError, ValueError, RuntimeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않은 인증 토큰입니다.",
            )
    try:
        if user is None:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
        )
    except Exception as exc:
        logger.error("인증 처리 중 DB 오류: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
        )
    return user


def is_designated_club_admin(db: Session, user_id: str) -> bool:
    """온보딩 개방 대상, 지정 관리자 또는 현직 회장인지 확인한다."""
    from src.models.club_admin import ClubAdmin
    from src.models.club_member import ClubMember

    if settings.ALLOW_SELF_SERVICE_CLUB_ADMIN:
        return True
    if db.query(ClubAdmin.user_id).filter(ClubAdmin.user_id == user_id).first() is not None:
        return True
    return db.query(ClubMember.id).filter(
        ClubMember.user_id == user_id,
        ClubMember.role == "president",
        ClubMember.status == "active",
    ).first() is not None


def require_club_admin(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """온보딩 개방 대상 또는 운영자가 지정한 동아리 관리자만 통과시킨다."""
    if not is_designated_club_admin(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="지정된 동아리 관리자만 접근할 수 있습니다.",
        )
    return current_user


def require_club_president(club_id: str, current_user=Depends(require_club_admin), db: Session = Depends(get_db)):
    """지정 관리자이면서 해당 동아리의 현직 회장인지 확인한다."""
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
