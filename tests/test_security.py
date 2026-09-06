import io
from unittest.mock import MagicMock, patch

from supabase_auth.errors import AuthApiError

from src.core.config import settings
from src.core.security import hash_password
from src.models.user import EmailVerification, User
from src.services import auth_service


def test_email_verification_code_is_hashed_at_rest(client, db):
    with patch("src.services.auth_service.send_verification_email") as send:
        response = client.post(
            "/api/v1/auth/email-verify/send", json={"email": "secure@cju.ac.kr"}
        )

    plain_code = send.call_args.args[1]
    record = db.query(EmailVerification).filter_by(email="secure@cju.ac.kr").one()
    assert response.status_code == 200
    assert len(record.code) == 64
    assert record.code != plain_code


def test_email_send_cooldown_returns_429(client):
    with patch("src.services.auth_service.send_verification_email"):
        first = client.post(
            "/api/v1/auth/email-verify/send", json={"email": "cooldown@cju.ac.kr"}
        )
        second = client.post(
            "/api/v1/auth/email-verify/send", json={"email": "cooldown@cju.ac.kr"}
        )

    assert first.status_code == 200
    assert second.status_code == 429


def test_verification_code_locks_after_max_failures(client, db):
    with patch("src.services.auth_service.send_verification_email"):
        client.post(
            "/api/v1/auth/email-verify/send", json={"email": "attempts@cju.ac.kr"}
        )

    with patch.object(settings, "EMAIL_VERIFY_MAX_ATTEMPTS", 2):
        for _ in range(2):
            response = client.post(
                "/api/v1/auth/email-verify/confirm",
                json={"email": "attempts@cju.ac.kr", "code": "000000"},
            )

    record = db.query(EmailVerification).filter_by(email="attempts@cju.ac.kr").one()
    assert response.status_code == 400
    assert record.is_used is True
    assert record.attempt_count == 2


def test_confirmed_email_uses_hashed_one_time_registration_token(client, db):
    with patch("src.services.auth_service.send_verification_email") as send:
        client.post(
            "/api/v1/auth/email-verify/send",
            json={"email": "one-time@cju.ac.kr"},
        )

    confirm = client.post(
        "/api/v1/auth/email-verify/confirm",
        json={"email": "one-time@cju.ac.kr", "code": send.call_args.args[1]},
    )
    token = confirm.json()["verification_token"]
    record = db.query(EmailVerification).filter_by(email="one-time@cju.ac.kr").one()

    assert confirm.status_code == 200
    assert len(token) >= 32
    assert record.confirmation_token_hash is not None
    assert record.confirmation_token_hash != token

def test_resend_invalidates_previously_confirmed_token(client, db):
    email = "resend-token@cju.ac.kr"
    with patch("src.services.auth_service.send_verification_email") as send:
        client.post("/api/v1/auth/email-verify/send", json={"email": email})
    confirm = client.post(
        "/api/v1/auth/email-verify/confirm",
        json={"email": email, "code": send.call_args.args[1]},
    )
    assert confirm.status_code == 200

    with (
        patch("src.services.auth_service.send_verification_email"),
        patch.object(settings, "EMAIL_SEND_COOLDOWN_SECONDS", 0),
    ):
        resend = client.post("/api/v1/auth/email-verify/send", json={"email": email})

    old_record = db.query(EmailVerification).filter_by(email=email).order_by(
        EmailVerification.created_at.asc()
    ).first()
    assert resend.status_code == 200
    assert old_record.confirmation_token_hash is None


def test_simple_logout_does_not_call_supabase(client, auth_headers):
    with patch("src.routers.v1.auth.auth_service.revoke_supabase_session") as revoke:
        response = client.post("/api/v1/auth/logout", headers=auth_headers)

    assert response.status_code == 204
    revoke.assert_not_called()


def test_rejects_file_whose_content_does_not_match_mime(client, auth_headers):
    response = client.post(
        "/api/v1/clubs/images",
        headers=auth_headers,
        files={"file": ("fake.jpg", io.BytesIO(b"not an image"), "image/jpeg")},
    )
    assert response.status_code == 400


def test_existing_unlinked_auth_user_is_repaired_on_login(db):
    user = User(
        student_id="REPAIR001",
        password_hash=hash_password("Password1!"),
        name="이관사용자",
        email="repair@cju.ac.kr",
        email_verified=True,
    )
    db.add(user)
    db.commit()

    existing = MagicMock()
    existing.id = "00000000-0000-0000-0000-000000000099"
    existing.email = user.email
    admin_client = MagicMock()
    admin_client.auth.admin.list_users.return_value = [existing]

    auth_client = MagicMock()
    successful = MagicMock()
    successful.session = MagicMock()
    successful.user = existing
    auth_client.auth.sign_in_with_password.side_effect = [
        AuthApiError("Invalid login credentials", 400, "invalid_credentials"),
        successful,
    ]

    with (
        patch.object(settings, "SUPABASE_SERVICE_KEY", "test-secret"),
        patch("src.services.auth_service.get_supabase_admin_client", return_value=admin_client),
        patch("src.services.auth_service.create_supabase_auth_client", return_value=auth_client),
    ):
        session = auth_service.create_supabase_session(db, user, "Password1!")

    assert session is successful.session
    assert user.auth_user_id == str(existing.id)
    admin_client.auth.admin.update_user_by_id.assert_called_once_with(
        str(existing.id),
        {"password": auth_service._supabase_password(user.id, "Password1!")},
    )
