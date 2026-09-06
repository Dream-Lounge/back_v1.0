import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from supabase_auth.errors import AuthApiError
from sqlalchemy.exc import OperationalError as DBOperationalError
from sqlalchemy.orm import Session

from src.core.security import create_access_token
from src.core.dependencies import get_current_user
from src.db.session import get_db
from src.schemas.user import (
    EmailVerifySendRequest,
    EmailVerifyConfirmRequest,
    EmailVerifyConfirmResponse,
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


@router.post("/email-verify/send", status_code=status.HTTP_200_OK)
def send_email_verification(
    body: EmailVerifySendRequest, request: Request, db: Session = Depends(get_db)
):
    """청주대 이메일로 6자리 인증번호 발송."""
    try:
        auth_service.send_verification_code(
            db, str(body.email), get_rate_limit_client_ip(request)
        )
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except DBOperationalError as e:
        logger.error(f"DB 연결 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="데이터베이스 연결에 실패했습니다. 서버 설정을 확인해주세요.",
        )
    except Exception as e:
        logger.error(f"이메일 발송 중 오류 발생: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="이메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )
    return {"message": "인증번호가 발송되었습니다."}


@router.post(
    "/email-verify/confirm",
    response_model=EmailVerifyConfirmResponse,
    status_code=status.HTTP_200_OK,
)
def confirm_email_verification(body: EmailVerifyConfirmRequest, db: Session = Depends(get_db)):
    """인증번호 검증."""
    try:
        token = auth_service.confirm_verification_code(db, str(body.email), body.code)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except DBOperationalError as e:
        logger.error(f"DB 연결 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="데이터베이스 연결에 실패했습니다. 서버 설정을 확인해주세요.",
        )
    return EmailVerifyConfirmResponse(
        message="이메일 인증이 완료되었습니다.",
        verification_token=token,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    """가두모집용 간편 회원가입 (학번 + 숫자 4자리 PIN)."""
    try:
        auth_service.enforce_registration_rate_limit(
            db,
            body.student_id,
            body.student_id,
            get_rate_limit_client_ip(request),
        )
        user = auth_service.register_user(db, body)
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except DBOperationalError as e:
        logger.error(f"DB 연결 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="데이터베이스 연결에 실패했습니다. 서버 설정을 확인해주세요.",
        )
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
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
        # 간편 계정은 Supabase Auth를 생성하지 않고 백엔드 JWT만 사용한다.
        session = (
            auth_service.create_supabase_session(db, user, body.password)
            if user.auth_user_id
            else None
        )
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
        return TokenResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            user=UserInfo.model_validate(user),
        )
    token = create_access_token({"sub": user.id})
    refresh_token = auth_service.create_local_session(db, user)
    return TokenResponse(
        access_token=token,
        refresh_token=refresh_token,
        user=UserInfo.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    """회전형 자체 refresh token으로 access token을 재발급한다."""
    try:
        refresh_token, user = auth_service.rotate_local_session(db, body.refresh_token)
        return TokenResponse(
            access_token=create_access_token({"sub": user.id}),
            refresh_token=refresh_token,
            user=UserInfo.model_validate(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.warning("세션 갱신 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션을 갱신할 수 없습니다. 다시 로그인해주세요.",
        )
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    body: LogoutRequest | None = None,
):
    """현재 브라우저의 Supabase 또는 자체 JWT 갱신 세션을 폐기한다."""
    try:
        if current_user.auth_user_id:
            auth_service.revoke_supabase_session(credentials.credentials)
        elif body and body.refresh_token:
            auth_service.revoke_local_session(db, current_user.id, body.refresh_token)
    except Exception as exc:
        logger.warning("Supabase 세션 폐기 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="로그아웃 처리에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )


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
