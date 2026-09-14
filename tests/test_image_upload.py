"""동아리 이미지 업로드 테스트 (Supabase Storage mock)."""
import io
from unittest.mock import MagicMock, patch

FAKE_PUBLIC_URL = "https://storage.example.com/club-images/clubs/test.jpg"


def upload_url(club_id: str) -> str:
    return f"/api/v1/clubs/{club_id}/images"


def _mock_supabase(public_url: str = FAKE_PUBLIC_URL):
    mock = MagicMock()
    mock.storage.from_().upload.return_value = {}
    mock.storage.from_().get_public_url.return_value = public_url
    return mock


def _jpeg_file(name: str = "photo.jpg", size: int = 1024):
    return (name, io.BytesIO(b"\xff\xd8\xff" + b"\x00" * size), "image/jpeg")


def test_removed_managed_image_is_deleted_from_storage():
    from src.core.config import settings
    from src.utils.storage import delete_managed_club_images

    storage = _mock_supabase()
    managed_url = (
        f"https://project.supabase.co/storage/v1/object/public/"
        f"{settings.SUPABASE_STORAGE_BUCKET}/clubs/club-id/old.jpg"
    )
    with (
        patch.object(settings, "SUPABASE_SERVICE_KEY", "test-service-key"),
        patch("src.utils.storage.get_supabase_admin_client", return_value=storage),
    ):
        delete_managed_club_images({managed_url, "https://example.com/external.jpg"})

    storage.storage.from_.return_value.remove.assert_called_once_with(
        ["clubs/club-id/old.jpg"]
    )


class TestImageUpload:
    def test_onboarding_user_can_upload_before_club_creation(self, client, designated_admin_headers):
        storage = _mock_supabase()
        with (
            patch("src.core.config.FORCE_SELF_SERVICE_CLUB_ADMIN_OPEN", True),
            patch("src.utils.storage.get_supabase_admin_client", return_value=storage),
        ):
            resp = client.post(
                "/api/v1/clubs/images",
                headers=designated_admin_headers,
                files={"file": _jpeg_file()},
            )

        assert resp.status_code == 200
        upload_path = storage.storage.from_.return_value.upload.call_args.kwargs["path"]
        assert upload_path.startswith("clubs/pending/")

    def test_regular_user_cannot_upload_before_club_creation(self, client, auth_headers):
        resp = client.post(
            "/api/v1/clubs/images", headers=auth_headers, files={"file": _jpeg_file()}
        )
        assert resp.status_code == 403

    def test_precreation_upload_requires_auth(self, client):
        resp = client.post("/api/v1/clubs/images", files={"file": _jpeg_file()})
        assert resp.status_code in (401, 403)

    def test_upload_success(self, client, president_headers, seeded_club):
        storage = _mock_supabase()
        with patch("src.utils.storage.get_supabase_admin_client", return_value=storage):
            resp = client.post(upload_url(seeded_club["club"].id), headers=president_headers, files={"file": _jpeg_file()})
        assert resp.status_code == 200
        assert resp.json()["image_url"] == FAKE_PUBLIC_URL
        assert storage.storage.from_.return_value.upload.call_args.kwargs["file_options"]["cache-control"] == "31536000"

    def test_requires_auth(self, client, seeded_club):
        resp = client.post(upload_url(seeded_club["club"].id), files={"file": _jpeg_file()})
        assert resp.status_code in (401, 403)

    def test_rejects_regular_member(self, client, auth_headers, seeded_club):
        resp = client.post(upload_url(seeded_club["club"].id), headers=auth_headers, files={"file": _jpeg_file()})
        assert resp.status_code == 403

    def test_rejects_unsupported_type(self, client, president_headers, seeded_club):
        with patch("src.utils.storage.get_supabase_admin_client", return_value=_mock_supabase()):
            resp = client.post(
                upload_url(seeded_club["club"].id),
                headers=president_headers,
                files={"file": ("doc.pdf", io.BytesIO(b"pdf content"), "application/pdf")},
            )
        assert resp.status_code == 400
        assert "파일 형식" in resp.json()["detail"]

    def test_rejects_oversized_file(self, client, president_headers, seeded_club):
        big = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 + 1))
        with patch("src.utils.storage.get_supabase_admin_client", return_value=_mock_supabase()):
            resp = client.post(
                upload_url(seeded_club["club"].id),
                headers=president_headers,
                files={"file": ("big.jpg", big, "image/jpeg")},
            )
        assert resp.status_code == 400
        assert "5MB" in resp.json()["detail"]

    def test_accepts_png(self, client, president_headers, seeded_club):
        with patch("src.utils.storage.get_supabase_admin_client", return_value=_mock_supabase()):
            resp = client.post(
                upload_url(seeded_club["club"].id),
                headers=president_headers,
                files={"file": ("cover.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
            )
        assert resp.status_code == 200

    def test_accepts_webp(self, client, president_headers, seeded_club):
        with patch("src.utils.storage.get_supabase_admin_client", return_value=_mock_supabase()):
            resp = client.post(
                upload_url(seeded_club["club"].id),
                headers=president_headers,
                files={"file": ("cover.webp", io.BytesIO(b"RIFF....WEBP"), "image/webp")},
            )
        assert resp.status_code == 200

    def test_returned_url_usable_in_club_update(self, client, president_headers, seeded_club):
        """회장이 업로드한 URL을 자신의 동아리 수정에 사용할 수 있어야 한다."""
        with patch("src.utils.storage.get_supabase_admin_client", return_value=_mock_supabase()):
            upload_resp = client.post(upload_url(seeded_club["club"].id), headers=president_headers, files={"file": _jpeg_file()})

        image_url = upload_resp.json()["image_url"]
        club_resp = client.patch(f"/api/v1/clubs/{seeded_club['club'].id}", headers=president_headers, json={
            "image_url": image_url,
        })
        assert club_resp.status_code == 200
        assert club_resp.json()["image_url"] == image_url

    def test_storage_error_returns_503(self, client, president_headers, seeded_club):
        mock = MagicMock()
        mock.storage.from_().upload.side_effect = Exception("Storage unavailable")

        with patch("src.utils.storage.get_supabase_admin_client", return_value=mock):
            resp = client.post(upload_url(seeded_club["club"].id), headers=president_headers, files={"file": _jpeg_file()})
        assert resp.status_code == 503
