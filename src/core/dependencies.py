from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from supabase_auth.errors import AuthApiError
import logging
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.core.security import decode_access_token

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
        # Supabase access token은 프로젝트 서명키로 검증해야 하므로 Auth
        # 서버에서 사용자 정보를 검증하고 로컬 프로필과 연결한다.
        try:
            from src.utils.supabase_client import create_supabase_auth_client

            auth_response = create_supabase_auth_client().auth.get_user(
                access_token
            )
            auth_user = auth_response.user
            if not auth_user:
                raise ValueError
            user = db.query(User).filter(
                User.auth_user_id == str(auth_user.id)
            ).first()
        except (AuthApiError, ValueError, RuntimeError):
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
