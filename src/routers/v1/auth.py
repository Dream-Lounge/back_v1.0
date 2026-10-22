import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import OperationalError as DBOperationalError
from sqlalchemy.orm import Session
from supabase_auth.errors import AuthApiError

from src.core.config import settings
from src.core.dependencies import bearer, get_current_user, is_designated_club_admin
from src.core.security import create_access_token
from src.db.session import get_db
from src.schemas.user import (
    EmailChangeRequest,
    EmailChangeVerificationRequest,
    EmailResendRequest,
    EmailVerificationRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    PasswordChangeRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserCreate,
    UserInfo,
    UserInterestsResponse,
    UserInterestsUpdate,
    UserProfileUpdate,
    UserResponse,
)
from src.services import auth_service
from src.utils.client_ip import get_rate_limit_client_ip
from src.utils.device import request_device_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_COOKIE = "dreamlounge_access"
REFRESH_COOKIE = "dreamlounge_refresh"


def _user_info(db: Session, user) -> UserInfo:
    return UserInfo(
        id=user.id,
        student_id=user.student_id,
        name=user.name,
        phone=user.phone,
        department=user.department,
        email=user.email,
        email_verified=user.email_verified,
        onboarding_completed=user.onboarding_completed_at is not None,
        guide_seen=user.guide_seen_at is not None,
        is_club_admin=is_designated_club_admin(db, user.id),
        platform_roles=auth_service.get_active_platform_roles(db, user.id),
    )


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


def _get_device_id(request: Request) -> str:
    """공유 공인 IP 대신 브라우저 설치 단위를 구분하는 불투명 식별자."""
    return request_device_id(request)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """실제 이메일 인증메일을 발송하며 회원가입. 인증 전에는 로그인할 수 없습니다."""
    try:
        auth_service.enforce_registration_rate_limit(
            db,
            body.student_id,
            get_rate_limit_client_ip(request),
            _get_device_id(request),
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


@router.post("/email/verify", response_model=MessageResponse)
def verify_email(body: EmailVerificationRequest, db: Session = Depends(get_db)):
    """이메일로 받은 6자리 OTP를 확인하고 계정을 활성화합니다."""
    try:
        auth_service.verify_signup_email(db, str(body.email), body.token)
    except AuthApiError as e:
        logger.info("이메일 인증 실패: code=%s", e.code)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인증번호가 올바르지 않거나 만료되었습니다.",
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return MessageResponse(message="이메일 인증이 완료되었습니다. 로그인해주세요.")


@router.post("/email/resend", response_model=MessageResponse)
def resend_email(
    body: EmailResendRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """가입 확인 메일 재발송. 계정 존재 여부와 관계없이 같은 응답을 반환합니다."""
    try:
        auth_service.resend_signup_email(
            db,
            str(body.email),
            get_rate_limit_client_ip(request),
            _get_device_id(request),
        )
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except AuthApiError as e:
        logger.warning("Supabase 인증메일 재발송 실패: code=%s", e.code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증메일을 발송할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )
    except RuntimeError as e:
        logger.error("인증메일 재발송 설정 오류: %s", e)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    return MessageResponse(
        message="인증 대기 중인 계정이면 이메일을 다시 발송했습니다."
    )


@router.post("/email/change", response_model=MessageResponse)
def change_email(
    body: EmailChangeRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """새 학생 이메일로 변경 확인 메일을 발송합니다."""
    access_token = (
        credentials.credentials if credentials is not None
        else request.cookies.get(ACCESS_COOKIE)
    )
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not access_token or not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 변경을 위해 다시 로그인해주세요.",
        )
    try:
        auth_service.request_email_change(
            db,
            current_user,
            new_email=str(body.new_email),
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (AuthApiError, RuntimeError) as e:
        logger.warning("이메일 변경 요청 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="이메일 변경 인증을 시작할 수 없습니다.",
        )
    return MessageResponse(message="새 이메일로 변경 인증메일을 발송했습니다.")


@router.post("/email/change/verify", response_model=MessageResponse)
def verify_changed_email(
    body: EmailChangeVerificationRequest,
    db: Session = Depends(get_db),
):
    try:
        auth_service.verify_email_change(db, str(body.new_email), body.token)
    except (ValueError, AuthApiError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인증번호가 올바르지 않거나 만료되었습니다.",
        ) from e
    return MessageResponse(message="학생 이메일 변경이 완료되었습니다. 다시 로그인해주세요.")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """학번 + 비밀번호 로그인 → JWT + 사용자 정보 반환."""
    client_ip = get_rate_limit_client_ip(request)
    device_id = _get_device_id(request)
    try:
        auth_service.enforce_login_rate_limit(db, body.student_id, client_ip, device_id)
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    user = auth_service.authenticate_user(db, body.student_id, body.password)
    if not user:
        rate_limit_message = auth_service.record_login_failure(
            db, student_id=body.student_id, client_ip=client_ip, device_id=device_id
        )
        if rate_limit_message:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=rate_limit_message,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="학번 또는 비밀번호가 올바르지 않습니다.",
        )
    if auth_service.requires_email_verification(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이메일 인증을 완료해주세요.",
        )
    try:
        # 기존 간편 계정도 최초 로그인 시 Supabase Auth에 자동 연결한다.
        session = auth_service.create_supabase_session(db, user, body.password)
    except AuthApiError as e:
        if e.code == "invalid_credentials":
            rate_limit_message = auth_service.record_login_failure(
                db, student_id=body.student_id, client_ip=client_ip, device_id=device_id
            )
            if rate_limit_message:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=rate_limit_message,
                )
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
            user=_user_info(db, user),
        )
    token = create_access_token({"sub": user.id})
    refresh_token = auth_service.create_local_session(db, user)
    _set_session_cookies(response, token, refresh_token)
    return TokenResponse(
        user=_user_info(db, user),
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
        device_id = _get_device_id(request)
        auth_service.enforce_refresh_rate_limit(
            db,
            device_id=device_id,
            client_ip=get_rate_limit_client_ip(request),
        )
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
                user=_user_info(db, user),
            )
        except ValueError:
            session, user = auth_service.refresh_supabase_session(db, supplied_refresh_token)
            _set_session_cookies(response, session.access_token, session.refresh_token)
            return TokenResponse(
                user=_user_info(db, user),
            )
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
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
def get_me(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """현재 로그인한 사용자 정보 조회."""
    return _user_info(db, current_user)


@router.patch("/me", response_model=UserInfo)
def update_me(
    body: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user = auth_service.update_profile(db, current_user, body)
    return _user_info(db, user)


@router.post("/me/guide-seen", response_model=UserInfo)
def mark_guide_seen(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    return _user_info(db, auth_service.mark_guide_seen(db, current_user))


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    access_token = (
        credentials.credentials if credentials is not None
        else request.cookies.get(ACCESS_COOKIE)
    )
    try:
        auth_service.change_password(
            db, current_user, body.current_password, body.new_password, access_token
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (AuthApiError, RuntimeError) as exc:
        logger.warning("비밀번호 변경 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="비밀번호를 변경할 수 없습니다. 잠시 후 다시 시도해주세요.",
        )
    _clear_session_cookies(response)


@router.get("/me/interests", response_model=UserInterestsResponse)
def get_my_interests(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    interests = auth_service.get_interests(db, current_user.id)
    return {
        "interests": interests,
        "onboarding_completed": current_user.onboarding_completed_at is not None,
    }


@router.put("/me/interests", response_model=UserInterestsResponse)
def update_my_interests(
    body: UserInterestsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    interests = auth_service.replace_interests(db, current_user, body)
    return {
        "interests": interests,
        "onboarding_completed": current_user.onboarding_completed_at is not None,
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_me(
    response: Response,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """현재 로그인한 사용자 회원탈퇴."""
    try:
        access_token = (
            credentials.credentials if credentials is not None
            else request.cookies.get(ACCESS_COOKIE)
        )
        auth_service.withdraw_user(db, current_user, access_token)
        _clear_session_cookies(response)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
