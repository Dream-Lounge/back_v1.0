import logging
import uuid
from urllib.parse import unquote, urlparse
from fastapi import UploadFile

from src.core.config import settings
from src.utils.supabase_client import get_supabase_admin_client

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def _detect_image_type(contents: bytes) -> tuple[str, str] | None:
    """신뢰할 수 없는 Content-Type 대신 파일 시그니처로 이미지 형식을 판별한다."""
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if contents.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", "gif"
    if len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


async def _upload_image(file: UploadFile, path_prefix: str) -> str:
    """검증한 이미지를 지정된 서버 관리 경로에 업로드한다."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError("지원하지 않는 파일 형식입니다. jpg, png, webp, gif만 허용됩니다.")

    contents = await file.read(MAX_FILE_SIZE + 1)

    if len(contents) > MAX_FILE_SIZE:
        raise ValueError("파일 크기는 5MB 이하여야 합니다.")

    detected = _detect_image_type(contents)
    if not detected or detected[0] != file.content_type:
        raise ValueError("파일 내용과 이미지 형식이 일치하지 않습니다.")
    detected_content_type, ext = detected
    path = f"{path_prefix}/{uuid.uuid4()}.{ext}"

    client = get_supabase_admin_client()
    try:
        client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).upload(
            path=path,
            file=contents,
            # UUID 파일명은 덮어쓰지 않으므로 브라우저/CDN이 안전하게 장기 캐시할 수 있다.
            file_options={
                "content-type": detected_content_type,
                "cache-control": "31536000",
            },
        )
    except Exception as e:
        logger.error("Supabase Storage upload failed: %s", e, exc_info=True)
        msg = str(e)
        if "Bucket not found" in msg:
            raise RuntimeError(
                f"Supabase Storage 버킷 '{settings.SUPABASE_STORAGE_BUCKET}'이 존재하지 않습니다. "
                "Supabase 대시보드 → Storage에서 버킷을 생성해주세요."
            ) from e
        raise

    return client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).get_public_url(path)


async def upload_club_image(file: UploadFile, club_id: str) -> str:
    """기존 동아리의 이미지를 해당 동아리 경로에 업로드한다."""
    return await _upload_image(file, f"clubs/{club_id}")


async def upload_pending_club_image(file: UploadFile, user_id: str) -> str:
    """동아리 생성 전 이미지를 로그인 사용자의 임시 경로에 업로드한다."""
    return await _upload_image(file, f"clubs/pending/{user_id}")


def _managed_storage_path(url: str) -> str | None:
    """현재 공개 버킷 URL만 안전한 삭제 대상 경로로 변환한다."""
    marker = f"/storage/v1/object/public/{settings.SUPABASE_STORAGE_BUCKET}/"
    path = unquote(urlparse(url).path)
    if marker not in path:
        return None
    object_path = path.split(marker, 1)[1].lstrip("/")
    if not object_path.startswith("clubs/") or ".." in object_path.split("/"):
        return None
    return object_path


def delete_managed_club_images(urls: set[str]) -> None:
    """교체되어 더 이상 참조하지 않는 관리형 이미지를 최선 노력으로 삭제한다."""
    if not settings.SUPABASE_SERVICE_KEY:
        return
    paths = sorted({path for url in urls if (path := _managed_storage_path(url))})
    if not paths:
        return
    try:
        get_supabase_admin_client().storage.from_(settings.SUPABASE_STORAGE_BUCKET).remove(paths)
    except Exception:
        # 동아리 정보 저장은 이미 성공했으므로 Storage 정리 실패로 되돌리지 않는다.
        logger.exception("Supabase Storage orphan cleanup failed: paths=%s", paths)


def cleanup_pending_club_images(user_id: str, keep_urls: set[str]) -> None:
    """동아리 생성 성공 후 선택하지 않은 해당 관리자의 임시 이미지를 정리한다."""
    if not settings.SUPABASE_SERVICE_KEY:
        return
    prefix = f"clubs/pending/{user_id}"
    keep_paths = {
        path for url in keep_urls if (path := _managed_storage_path(url))
    }
    try:
        bucket = get_supabase_admin_client().storage.from_(settings.SUPABASE_STORAGE_BUCKET)
        objects = bucket.list(prefix, {"limit": 1000})
        stale_paths = []
        for item in objects or []:
            name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
            if not name:
                continue
            path = f"{prefix}/{name}"
            if path not in keep_paths:
                stale_paths.append(path)
        if stale_paths:
            bucket.remove(stale_paths)
    except Exception:
        logger.exception("Supabase pending image cleanup failed: user_id=%s", user_id)
