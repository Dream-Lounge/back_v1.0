from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    payload = data.copy()
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # python-jose는 datetime을 정수 초로 변환한다. 비밀번호 변경과 토큰 발급이
    # 같은 초에 일어나도 선후를 판별할 수 있도록 직접 소수점 epoch를 저장한다.
    payload["iat"] = issued_at.timestamp()
    payload["exp"] = expire
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def create_email_verification_token(email: str, auth_user_id: str) -> str:
    """OTP 확인 결과를 최종 회원가입까지 안전하게 전달하는 단기 증명."""
    issued_at = datetime.now(timezone.utc)
    payload = {
        "type": "signup_email_verified",
        "email": email.strip().lower(),
        "auth_user_id": auth_user_id,
        "iat": issued_at.timestamp(),
        "exp": issued_at + timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_email_verification_token(token: str) -> tuple[str, str]:
    """이메일 인증 증명을 검증하고 (이메일, Supabase 사용자 ID)를 반환한다."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise ValueError("이메일 인증이 만료되었습니다. 인증번호를 다시 받아주세요.") from exc
    if payload.get("type") != "signup_email_verified":
        raise ValueError("올바르지 않은 이메일 인증 정보입니다.")
    email = str(payload.get("email") or "").strip().lower()
    auth_user_id = str(payload.get("auth_user_id") or "").strip()
    if not email or not auth_user_id:
        raise ValueError("올바르지 않은 이메일 인증 정보입니다.")
    return email, auth_user_id
