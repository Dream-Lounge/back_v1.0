import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from supabase_auth.errors import AuthApiError
from sqlalchemy.exc import OperationalError as DBOperationalError
from sqlalchemy.orm import Session

from src.core.security import create_access_token
from src.core.config import settings
from src.core.dependencies import get_current_user
from src.db.session import get_db
from src.schemas.user import (
    UserCreate,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserInfo,
    UserResponse,
)
from src.services import auth_service
from src.utils.client_ip import get_rate_limit_client_ip
from src.core.dependencies import bearer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_COOKIE = "dreamlounge_access"
REFRESH_COOKIE = "dreamlounge_refresh"


def _cookie_path(api_path: str) -> str:
    """브라우저에 보이는 외부 경로 접두사를 쿠키 Path에 반영한다."""
    return f"{settings.COOKIE_PATH_PREFIX}{api_path}"


def _set_session_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    secure = settings.ENVIRONMENT.lower() == "production"
    same_site = "none" if secure else "lax"
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path=_cookie_path("/api/v1"),
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path=_cookie_path("/api/v1/auth"),
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path=_cookie_path("/api/v1"))
    response.delete_cookie(REFRESH_COOKIE, path=_cookie_path("/api/v1/auth"))


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    """학번 + 8자 이상이며 특수문자를 포함한 비밀번호로 회원가입."""
    try:
        auth_service.enforce_registration_rate_limit(
            db,
            body.student_id,
            get_rate_limit_client_ip(request),
        )
        user = auth_service.register_user(db, body)
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (AuthApiError, RuntimeError) as e:
        logger.error("Supabase Auth 회원 생성 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증 계정을 생성할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )
    except DBOperationalError as e:
        logger.error(f"DB 연결 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="데이터베이스 연결에 실패했습니다. 서버 설정을 확인해주세요.",
        )
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """학번 + 비밀번호 로그인 → JWT + 사용자 정보 반환."""
    client_ip = get_rate_limit_client_ip(request)
    try:
        auth_service.enforce_login_rate_limit(db, body.student_id, client_ip)
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    user = auth_service.authenticate_user(db, body.student_id, body.password)
    if not user:
        auth_service.record_login_failure(db, body.student_id, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="학번 또는 비밀번호가 올바르지 않습니다.",
        )
    try:
        # 기존 간편 계정도 최초 로그인 시 Supabase Auth에 자동 연결한다.
        session = auth_service.create_supabase_session(db, user, body.password)
    except AuthApiError as e:
        if e.code == "invalid_credentials":
            auth_service.record_login_failure(db, body.student_id, client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="학번 또는 비밀번호가 올바르지 않습니다.",
            )
        logger.warning("Supabase 로그인 실패: code=%s", e.code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )
    except RuntimeError as e:
        logger.error("인증 계정 연결 실패: %s", e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    auth_service.clear_login_failures(db, body.student_id)
    if session:
        _set_session_cookies(response, session.access_token, session.refresh_token)
        return TokenResponse(
            user=UserInfo.model_validate(user),
        )
    token = create_access_token({"sub": user.id})
    refresh_token = auth_service.create_local_session(db, user)
    _set_session_cookies(response, token, refresh_token)
    return TokenResponse(
        user=UserInfo.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(
    request: Request,
    response: Response,
    body: RefreshTokenRequest | None = None,
    db: Session = Depends(get_db),
):
    """Supabase 또는 기존 자체 refresh token으로 세션을 재발급한다."""
    try:
        supplied_refresh_token = (
            (body.refresh_token if body else None)
            or request.cookies.get(REFRESH_COOKIE)
        )
        if not supplied_refresh_token:
            raise ValueError("갱신 토큰이 없습니다.")
        try:
            refresh_token, user = auth_service.rotate_local_session(db, supplied_refresh_token)
            access_token = create_access_token({"sub": user.id})
            _set_session_cookies(response, access_token, refresh_token)
            return TokenResponse(
                user=UserInfo.model_validate(user),
            )
        except ValueError:
            session, user = auth_service.refresh_supabase_session(db, supplied_refresh_token)
            _set_session_cookies(response, session.access_token, session.refresh_token)
            return TokenResponse(
                user=UserInfo.model_validate(user),
            )
    except (ValueError, AuthApiError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.warning("세션 갱신 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션을 갱신할 수 없습니다. 다시 로그인해주세요.",
        )
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    body: LogoutRequest | None = None,
):
    """현재 브라우저의 Supabase 또는 자체 JWT 갱신 세션을 폐기한다."""
    try:
        if current_user.auth_user_id:
            access_token = (
                credentials.credentials
                if credentials is not None
                else request.cookies.get(ACCESS_COOKIE)
            )
            if access_token:
                auth_service.revoke_supabase_session(access_token)
        else:
            refresh_token = request.cookies.get(REFRESH_COOKIE) or (
                body.refresh_token if body else None
            )
            if refresh_token:
                auth_service.revoke_local_session(db, current_user.id, refresh_token)
    except Exception as exc:
        logger.warning("Supabase 세션 폐기 실패: %s", exc)
    finally:
        _clear_session_cookies(response)


@router.get("/me", response_model=UserInfo)
def get_me(current_user=Depends(get_current_user)):
    """현재 로그인한 사용자 정보 조회."""
    return current_user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_me(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """현재 로그인한 사용자 회원탈퇴."""
    try:
        auth_service.withdraw_user(db, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
