import ipaddress

from fastapi import Request

from src.core.config import settings


def get_rate_limit_client_ip(request: Request) -> str | None:
    """신뢰 프록시가 설정된 경우에만 전달 헤더를 속도 제한에 사용한다."""
    candidate = request.client.host if request.client else ""
    try:
        peer_ip = ipaddress.ip_address(candidate)
    except ValueError:
        peer_ip = None

    trusted_peer = peer_ip is not None and any(
        peer_ip in ipaddress.ip_network(cidr, strict=False)
        for cidr in settings.get_trusted_proxy_cidrs()
    )
    if settings.TRUST_PROXY_HEADERS and trusted_peer:
        candidate = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None
