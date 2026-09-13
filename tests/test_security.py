import io
from unittest.mock import MagicMock, patch

from jose import JWTError
from supabase_auth.errors import AuthApiError

from src.core.config import settings
from src.core.security import hash_password
from src.models.user import User
from src.models.club_admin import ClubAdmin
from src.services import auth_service


def test_supabase_access_token_is_verified_locally(client, db):
    user = User(
        auth_user_id="00000000-0000-0000-0000-000000000777",
        student_id="2021777777",
        password_hash=hash_password("Password1!"),
        name="로컬검증",
        email="2021777777@simple.dreamlounge.local",
        email_verified=False,
    )
    db.add(user)
    db.commit()

    with (
        patch(
            "src.core.dependencies.decode_access_token",
            side_effect=JWTError("not a local token"),
        ),
        patch(
            "src.core.dependencies.decode_supabase_access_token",
            return_value={"sub": user.auth_user_id},
        ) as local_verify,
        patch("src.utils.supabase_client.create_supabase_auth_client") as remote_client,
    ):
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer supabase-es256-token"},
        )

    assert response.status_code == 200
    assert response.json()["student_id"] == user.student_id
    local_verify.assert_called_once_with("supabase-es256-token")
    remote_client.assert_not_called()


def test_user_info_exposes_only_operator_designated_admin_status(
    client, auth_headers, president_headers
):
    regular = client.get("/api/v1/auth/me", headers=auth_headers)
    president = client.get("/api/v1/auth/me", headers=president_headers)

    assert regular.status_code == 200
    assert regular.json()["is_club_admin"] is False
    assert president.status_code == 200
    assert president.json()["is_club_admin"] is True


def test_removing_allowlist_immediately_revokes_admin_api_access(
    client, db, seeded_club, president_headers
):
    db.query(ClubAdmin).filter(
        ClubAdmin.user_id == seeded_club["president"].id
    ).delete()
    db.commit()

    response = client.patch(
        f"/api/v1/clubs/{seeded_club['club'].id}",
        headers=president_headers,
        json={"description": "권한 제거 후 수정 시도"},
    )

    assert response.status_code == 403
    assert "지정된 동아리 관리자" in response.json()["detail"]


def test_simple_logout_does_not_call_supabase(client, auth_headers):
    with patch("src.routers.v1.auth.auth_service.revoke_supabase_session") as revoke:
        response = client.post("/api/v1/auth/logout", headers=auth_headers)

    assert response.status_code == 204
    revoke.assert_not_called()


def test_registration_creates_auth_user_without_listing_all_users(db):
    admin_client = MagicMock()
    created_user = MagicMock()
    created_user.id = "00000000-0000-0000-0000-000000000123"
    created = MagicMock()
    created.user = created_user
    admin_client.auth.admin.create_user.return_value = created

    with (
        patch.object(settings, "SUPABASE_SERVICE_KEY", "test-secret"),
        patch("src.services.auth_service.get_supabase_admin_client", return_value=admin_client),
    ):
        user = auth_service.register_user(
            db,
            auth_service.UserCreate(student_id="2021999999", password="test1234!"),
        )

    assert user.auth_user_id == str(created_user.id)
    admin_client.auth.admin.create_user.assert_called_once()
    admin_client.auth.admin.list_users.assert_not_called()


def test_registration_releases_db_connection_before_auth_request(db):
    admin_client = MagicMock()
    created_user = MagicMock()
    created_user.id = "00000000-0000-0000-0000-000000000124"
    created = MagicMock(user=created_user)

    def create_user(_payload):
        assert not db.in_transaction()
        return created

    admin_client.auth.admin.create_user.side_effect = create_user

    with (
        patch.object(settings, "SUPABASE_SERVICE_KEY", "test-secret"),
        patch("src.services.auth_service.get_supabase_admin_client", return_value=admin_client),
    ):
        user = auth_service.register_user(
            db,
            auth_service.UserCreate(student_id="2021999998", password="test1234!"),
        )

    assert user.auth_user_id == str(created_user.id)


def test_rejects_file_whose_content_does_not_match_mime(client, president_headers, seeded_club):
    response = client.post(
        f"/api/v1/clubs/{seeded_club['club'].id}/images",
        headers=president_headers,
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
