from unittest.mock import patch

from starlette.requests import Request

from src.core.config import settings
from src.utils.client_ip import get_rate_limit_client_ip


def make_request(peer_ip: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer_ip, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })


def test_uses_digitalocean_connecting_ip_from_trusted_proxy():
    request = make_request("10.0.0.4", [
        (b"do-connecting-ip", b"203.0.113.20"),
        (b"x-forwarded-for", b"10.0.0.9"),
    ])
    with (
        patch.object(settings, "TRUST_PROXY_HEADERS", True),
        patch.object(settings, "TRUSTED_PROXY_CIDRS", '["10.0.0.0/8"]'),
    ):
        assert get_rate_limit_client_ip(request) == "203.0.113.20"


def test_ignores_spoofed_forwarded_headers_from_untrusted_peer():
    request = make_request("198.51.100.8", [
        (b"do-connecting-ip", b"203.0.113.20"),
        (b"x-forwarded-for", b"203.0.113.21"),
    ])
    with (
        patch.object(settings, "TRUST_PROXY_HEADERS", True),
        patch.object(settings, "TRUSTED_PROXY_CIDRS", '["10.0.0.0/8"]'),
    ):
        assert get_rate_limit_client_ip(request) == "198.51.100.8"
