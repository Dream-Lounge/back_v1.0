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
        # DigitalOcean App Platform은 실제 접속자 IP를 do-connecting-ip에
        # 전달한다. 일반 환경은 X-Forwarded-For의 첫 주소를 사용한다.
        candidate = request.headers.get("do-connecting-ip", "").strip()
        if not candidate:
            candidate = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None
