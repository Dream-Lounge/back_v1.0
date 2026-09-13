import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import JWTError, jwt

from src.core.config import settings
from src.utils import supabase_jwt


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes(32, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signing_material():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    numbers = private_key.public_key().public_numbers()
    public_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "use": "sig",
        "key_ops": ["verify"],
        "kid": "test-key",
        "x": _b64url_uint(numbers.x),
        "y": _b64url_uint(numbers.y),
    }
    return private_pem, public_jwk


def _token(private_pem: bytes, **overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "00000000-0000-0000-0000-000000000123",
        "aud": "authenticated",
        "role": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_pem,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )


def test_verifies_supabase_es256_token_locally():
    private_pem, public_jwk = _signing_material()
    supabase_jwt.clear_jwks_cache()

    with patch.object(supabase_jwt, "_download_jwks", return_value={"keys": [public_jwk]}) as download:
        payload = supabase_jwt.decode_supabase_access_token(_token(private_pem))
        supabase_jwt.decode_supabase_access_token(_token(private_pem))

    assert payload["sub"] == "00000000-0000-0000-0000-000000000123"
    download.assert_called_once()


def test_rejects_wrong_issuer():
    private_pem, public_jwk = _signing_material()
    supabase_jwt.clear_jwks_cache()

    with patch.object(supabase_jwt, "_download_jwks", return_value={"keys": [public_jwk]}):
        with pytest.raises(JWTError):
            supabase_jwt.decode_supabase_access_token(
                _token(private_pem, iss="https://other-project.supabase.co/auth/v1")
            )


def test_rejects_expired_token():
    private_pem, public_jwk = _signing_material()
    supabase_jwt.clear_jwks_cache()

    with patch.object(supabase_jwt, "_download_jwks", return_value={"keys": [public_jwk]}):
        with pytest.raises(JWTError):
            supabase_jwt.decode_supabase_access_token(
                _token(private_pem, exp=datetime.now(timezone.utc) - timedelta(seconds=1))
            )


def test_rejects_legacy_hs256_token_without_remote_fallback():
    token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000123",
            "aud": "authenticated",
            "role": "authenticated",
            "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "legacy-secret",
        algorithm="HS256",
    )

    with pytest.raises(JWTError):
        supabase_jwt.decode_supabase_access_token(token)
