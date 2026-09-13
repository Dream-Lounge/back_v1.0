import re
import secrets

from fastapi import Request


DEVICE_COOKIE = "dreamlounge_device"
DEVICE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}")


def resolve_device_id(request: Request) -> tuple[str, bool]:
    """요청의 브라우저 기기 ID와 새 쿠키 발급 필요 여부를 반환한다."""
    device_id = request.cookies.get(DEVICE_COOKIE, "")
    if DEVICE_ID_PATTERN.fullmatch(device_id):
        return device_id, False
    return secrets.token_urlsafe(32), True


def request_device_id(request: Request) -> str:
    """기기 식별 미들웨어가 저장한 ID를 라우터에서 사용한다."""
    device_id = getattr(request.state, "device_id", None)
    if isinstance(device_id, str) and DEVICE_ID_PATTERN.fullmatch(device_id):
        return device_id
    return resolve_device_id(request)[0]
