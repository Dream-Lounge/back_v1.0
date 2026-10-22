from datetime import datetime, timedelta, timezone

from jose import jwt
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
