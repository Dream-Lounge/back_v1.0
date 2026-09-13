from unittest.mock import MagicMock, patch
from fastapi import Response
from fastapi.testclient import TestClient

from src.core.config import settings
from src.routers.v1.auth import _clear_session_cookies, _set_session_cookies


# ── 헬스체크 ──────────────────────────────────────────────────────────────────

def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200


def test_session_cookie_paths_include_public_route_prefix():
    response = Response()
    with patch.object(settings, "COOKIE_PATH_PREFIX", "/back-v1-0"):
        _set_session_cookies(response, "access", "refresh")

    cookies = response.headers.getlist("set-cookie")
    assert any("Path=/back-v1-0/api/v1;" in cookie for cookie in cookies)
    assert any("Path=/back-v1-0/api/v1/auth;" in cookie for cookie in cookies)


def test_session_cookie_deletion_uses_public_route_prefix():
    response = Response()
    with patch.object(settings, "COOKIE_PATH_PREFIX", "/back-v1-0"):
        _clear_session_cookies(response)

    cookies = response.headers.getlist("set-cookie")
    assert any("Path=/back-v1-0/api/v1;" in cookie for cookie in cookies)
    assert any("Path=/back-v1-0/api/v1/auth;" in cookie for cookie in cookies)


# ── 회원가입 ───────────────────────────────────────────────────────────────────

class TestRegister:
    STUDENT_ID = "2021111111"

    def test_success(self, client, db):
        resp = client.post("/api/v1/auth/register", json={
            "student_id": self.STUDENT_ID,
            "password": "test1234!",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["student_id"] == self.STUDENT_ID
        assert "email" not in data
        assert "email_verified" not in data
        assert client.cookies.get("dreamlounge_device")

    def test_duplicate_student_id(self, client):
        payload = {"student_id": self.STUDENT_ID, "password": "test1234!"}
        client.post("/api/v1/auth/register", json=payload)
        resp = client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 400

    def test_rejects_password_shorter_than_eight_characters(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "student_id": self.STUDENT_ID,
            "password": "abc!123",
        })
        assert resp.status_code == 422

    def test_rejects_password_without_special_character(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "student_id": self.STUDENT_ID,
            "password": "password123",
        })
        assert resp.status_code == 422

    def test_accepts_lowercase_password_without_uppercase(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "student_id": self.STUDENT_ID,
            "password": "password!",
        })
        assert resp.status_code == 201

    def test_rejects_non_ten_digit_student_id(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "student_id": "student",
            "password": "test1234!",
        })
        assert resp.status_code == 422


# ── 로그인 ─────────────────────────────────────────────────────────────────────

class TestLogin:
    STUDENT_ID = "2021222222"
    PASSWORD = "test1234!"

    def _register(self, client, db):
        client.post("/api/v1/auth/register", json={
            "student_id": self.STUDENT_ID,
            "password": self.PASSWORD,
        })

    def test_success(self, client, db):
        self._register(client, db)
        resp = client.post("/api/v1/auth/login", json={
            "student_id": self.STUDENT_ID,
            "password": self.PASSWORD,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert data["token_type"] == "cookie"
        assert client.cookies.get("dreamlounge_access")
        assert client.cookies.get("dreamlounge_refresh")
        set_cookie = ",".join(resp.headers.get_list("set-cookie")).lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie

    def test_wrong_password(self, client, db):
        self._register(client, db)
        resp = client.post("/api/v1/auth/login", json={
            "student_id": self.STUDENT_ID,
            "password": "9999",
        })
        assert resp.status_code == 401

    def test_fifth_wrong_password_returns_lock_message(self, client, db):
        self._register(client, db)
        payload = {
            "student_id": self.STUDENT_ID,
            "password": "wrong-password!",
        }

        for _ in range(4):
            resp = client.post("/api/v1/auth/login", json=payload)
            assert resp.status_code == 401

        fifth = client.post("/api/v1/auth/login", json=payload)
        assert fifth.status_code == 429
        assert fifth.json()["detail"] == "로그인 5회 실패하여 10분 후 다시 시도해주세요!"

        locked = client.post("/api/v1/auth/login", json={
            "student_id": self.STUDENT_ID,
            "password": self.PASSWORD,
        })
        assert locked.status_code == 429
        assert locked.json()["detail"] == "로그인 5회 실패하여 10분 후 다시 시도해주세요!"

    def test_unknown_student_id(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "student_id": "9999999999",
            "password": "1234",
        })
        assert resp.status_code == 401

    def test_token_is_usable(self, client, db):
        """발급된 토큰으로 인증이 필요한 엔드포인트 접근 가능한지 확인."""
        self._register(client, db)
        client.post("/api/v1/auth/login", json={
            "student_id": self.STUDENT_ID,
            "password": self.PASSWORD,
        })
        token = client.cookies.get("dreamlounge_access")
        assert token

        resp = client.get("/api/v1/me/applications/drafts", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


class TestRefreshSession:
    def test_repeated_refresh_requests_are_rate_limited_per_device(self, client):
        with (
            patch.object(settings, "REFRESH_DEVICE_MAX_PER_10_MINUTES", 1),
            patch(
                "src.routers.v1.auth.auth_service.refresh_supabase_session",
                side_effect=ValueError("유효하지 않은 갱신 토큰입니다."),
            ),
        ):
            first = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "invalid-token"},
            )
            second = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "invalid-token"},
            )

        assert first.status_code == 401
        assert second.status_code == 429
        assert "세션 갱신 요청" in second.json()["detail"]

    def test_success(self, client, db):
        from src.models.user import User

        user = User(
            auth_user_id="00000000-0000-0000-0000-000000000010",
            student_id="REFRESH001",
            password_hash="unused",
            name="세션갱신",
            email="refresh@cju.ac.kr",
            email_verified=True,
        )
        db.add(user)
        db.commit()

        from src.services.auth_service import create_local_session

        old_refresh_token = create_local_session(db, user)
        resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh_token},
        )

        assert resp.status_code == 200
        assert resp.json()["token_type"] == "cookie"
        assert "access_token" not in resp.json()
        assert "refresh_token" not in resp.json()
        assert client.cookies.get("dreamlounge_refresh") != old_refresh_token

        reused = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh_token},
        )
        assert reused.status_code == 401

    def test_invalid_refresh_token(self, client):
        with patch(
            "src.routers.v1.auth.auth_service.refresh_supabase_session",
            side_effect=ValueError("유효하지 않은 갱신 토큰입니다."),
        ):
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "invalid-token"},
            )

        assert resp.status_code == 401

    def test_logout_revokes_local_refresh_token(self, client, db):
        from src.core.security import create_access_token
        from src.models.user import User
        from src.services.auth_service import create_local_session

        user = User(
            auth_user_id=None,
            student_id="LOGOUT0001",
            password_hash="unused",
            name="로그아웃",
            email="logout@simple.dreamlounge.local",
            email_verified=False,
        )
        db.add(user)
        db.commit()
        refresh_token = create_local_session(db, user)
        access_token = create_access_token({"sub": user.id})

        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 204
        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_response.status_code == 401


# ── 회원탈퇴 ───────────────────────────────────────────────────────────────────

class TestAccountWithdrawal:
    def test_withdraws_account_and_active_memberships(
        self, client, db, auth_headers, seeded_club
    ):
        from src.models.club_member import ClubMember
        from src.models.user import User

        user = db.query(User).filter(User.student_id == "2021000001").one()
        membership = ClubMember(
            club_id=seeded_club["club"].id,
            user_id=user.id,
            role="member",
            status="active",
        )
        db.add(membership)
        db.commit()

        resp = client.delete("/api/v1/auth/me", headers=auth_headers)

        assert resp.status_code == 204
        db.refresh(user)
        db.refresh(membership)
        assert user.is_active is False
        assert user.withdrawn_at is not None
        assert user.student_id.startswith("deleted_")
        assert user.email.endswith("@invalid.local")
        assert user.name == "탈퇴한 사용자"
        assert user.phone is None
        assert user.department is None
        assert user.auth_user_id is None
        assert membership.status == "withdrawn"
        assert membership.left_at is not None

    def test_withdrawn_account_cannot_use_token_or_login(
        self, client, db, auth_headers
    ):
        resp = client.delete("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 204

        me_resp = client.get("/api/v1/auth/me", headers=auth_headers)
        login_resp = client.post("/api/v1/auth/login", json={
            "student_id": "2021000001",
            "password": "Password1!",
        })

        assert me_resp.status_code == 401
        assert login_resp.status_code == 401

    def test_can_register_again_with_same_student_id(
        self, client, db, auth_headers
    ):
        from src.models.user import User

        original_user = db.query(User).filter(
            User.student_id == "2021000001",
        ).one()
        original_user_id = original_user.id

        withdraw_resp = client.delete("/api/v1/auth/me", headers=auth_headers)
        assert withdraw_resp.status_code == 204

        register_resp = client.post("/api/v1/auth/register", json={
            "student_id": "2021000001",
            "password": "newpass8!",
        })

        assert register_resp.status_code == 201
        assert register_resp.json()["id"] != original_user_id
        new_user = db.query(User).filter(User.student_id == "2021000001").one()
        assert new_user.email == "2021000001@simple.dreamlounge.local"
        assert new_user.is_active is True

    def test_active_president_must_transfer_role_first(
        self, client, db, president_headers, seeded_club
    ):
        president = seeded_club["president"]

        resp = client.delete("/api/v1/auth/me", headers=president_headers)

        assert resp.status_code == 409
        assert resp.json()["detail"] == (
            "동아리 회장은 다른 부원에게 회장 권한을 이전한 후 "
            "회원탈퇴할 수 있습니다."
        )
        db.refresh(president)
        assert president.is_active is True
        assert president.withdrawn_at is None

    def test_hard_deletes_linked_supabase_auth_user(self, db):
        from src.core.config import settings
        from src.models.user import User
        from src.services import auth_service

        user = User(
            auth_user_id="00000000-0000-0000-0000-000000000001",
            student_id="WITHDRAW001",
            password_hash="unused",
            name="탈퇴테스트",
            email="withdraw@cju.ac.kr",
            email_verified=True,
        )
        db.add(user)
        db.commit()

        auth_user_id = user.auth_user_id
        supabase = MagicMock()
        with (
            patch.object(settings, "SUPABASE_SERVICE_KEY", "test-service-key"),
            patch(
                "src.services.auth_service.get_supabase_admin_client",
                return_value=supabase,
            ),
        ):
            auth_service.withdraw_user(db, user)

        supabase.auth.admin.delete_user.assert_called_once_with(
            auth_user_id,
            should_soft_delete=False,
        )
        assert user.is_active is False
        assert user.auth_user_id is None

    def test_login_client_does_not_replace_admin_client_session(self, db):
        from src.core.config import settings
        from src.models.user import User
        from src.services import auth_service

        user = User(
            auth_user_id="00000000-0000-0000-0000-000000000002",
            student_id="LOGINCLIENT001",
            password_hash="unused",
            name="로그인테스트",
            email="login-client@cju.ac.kr",
            email_verified=True,
        )
        db.add(user)
        db.commit()

        auth_client = MagicMock()
        expected_session = MagicMock()
        auth_client.auth.sign_in_with_password.return_value.session = expected_session
        admin_client = MagicMock()

        with (
            patch.object(settings, "SUPABASE_SERVICE_KEY", "test-service-key"),
            patch(
                "src.services.auth_service.create_supabase_auth_client",
                return_value=auth_client,
            ),
            patch(
                "src.services.auth_service.get_supabase_admin_client",
                return_value=admin_client,
            ),
        ):
            session = auth_service.create_supabase_session(db, user, "Password1!")

        assert session is expected_session
        auth_client.auth.sign_in_with_password.assert_called_once_with({
            "email": user.email,
            "password": auth_service._supabase_password(user.id, "Password1!"),
        })
        admin_client.auth.sign_in_with_password.assert_not_called()
