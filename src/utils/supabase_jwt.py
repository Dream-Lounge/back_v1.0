import json
import threading
import time
from urllib.request import Request, urlopen

from jose import JWTError, jwt

from src.core.config import settings


_JWKS_MAX_BYTES = 64 * 1024
_jwks_lock = threading.Lock()
_jwks: dict | None = None
_jwks_expires_at = 0.0

def _issuer() -> str:
    return f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"


def _jwks_url() -> str:
    return f"{_issuer()}/.well-known/jwks.json"


def _download_jwks() -> dict:
    request = Request(
        _jwks_url(),
        headers={"Accept": "application/json", "User-Agent": "dreamlounge-backend"},
    )
    # 운영 설정이 SUPABASE_URL의 HTTPS 사용을 강제한다.
    with urlopen(request, timeout=5) as response:
        raw = response.read(_JWKS_MAX_BYTES + 1)
    if len(raw) > _JWKS_MAX_BYTES:
        raise JWTError("Supabase JWKS 응답이 너무 큽니다.")
    try:
        jwks = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise JWTError("Supabase JWKS 응답이 올바르지 않습니다.") from exc
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list) or not keys:
        raise JWTError("Supabase ES256 공개키가 없습니다.")
    return {"keys": keys}


def _get_jwks(force_refresh: bool = False) -> dict:
    global _jwks, _jwks_expires_at

    now = time.monotonic()
    if not force_refresh and _jwks is not None and now < _jwks_expires_at:
        return _jwks

    with _jwks_lock:
        now = time.monotonic()
        if not force_refresh and _jwks is not None and now < _jwks_expires_at:
            return _jwks
        loaded = _download_jwks()
        _jwks = loaded
        _jwks_expires_at = now + max(settings.SUPABASE_JWKS_CACHE_SECONDS, 60)
        return loaded


def _key_for_token(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise
    except Exception as exc:
        raise JWTError("JWT 헤더가 올바르지 않습니다.") from exc

    if header.get("alg") != "ES256":
        raise JWTError("허용되지 않은 Supabase JWT 알고리즘입니다.")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise JWTError("Supabase JWT key id가 없습니다.")

    for force_refresh in (False, True):
        keys = _get_jwks(force_refresh=force_refresh).get("keys", [])
        for key in keys:
            if (
                isinstance(key, dict)
                and key.get("kid") == kid
                and key.get("alg") == "ES256"
                and key.get("kty") == "EC"
            ):
                return key
    raise JWTError("Supabase JWT 공개키를 찾을 수 없습니다.")


def decode_supabase_access_token(token: str) -> dict:
    """Supabase ES256 access token을 공개키로 로컬 검증한다."""
    payload = jwt.decode(
        token,
        _key_for_token(token),
        algorithms=["ES256"],
        audience="authenticated",
        issuer=_issuer(),
        options={
            "require_aud": True,
            "require_exp": True,
            "require_iss": True,
            "require_sub": True,
        },
    )
    if payload.get("role") != "authenticated":
        raise JWTError("허용되지 않은 Supabase 사용자 역할입니다.")
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise JWTError("Supabase JWT subject가 없습니다.")
    return payload


def clear_jwks_cache() -> None:
    """테스트와 긴급 키 교체 시 프로세스의 공개키 캐시를 비운다."""
    global _jwks, _jwks_expires_at
    with _jwks_lock:
        _jwks = None
        _jwks_expires_at = 0.0
