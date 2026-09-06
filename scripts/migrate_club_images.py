"""Copy referenced club images to the new Supabase Storage project."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse, unquote

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from supabase import create_client

from migrate_club_catalog import database_url


def storage_settings(env_file: Path) -> tuple[str, str, str]:
    values = dotenv_values(env_file)
    url = values.get("SUPABASE_URL")
    key = values.get("SUPABASE_SERVICE_KEY")
    bucket = values.get("SUPABASE_STORAGE_BUCKET") or "club-images"
    if not url or not key:
        raise RuntimeError(f"Supabase Storage 서버 설정이 없습니다: {env_file}")
    return url.rstrip("/"), key, bucket


def object_path(public_url: str, bucket: str) -> str | None:
    marker = f"/storage/v1/object/public/{bucket}/"
    path = urlparse(public_url).path
    if marker not in path:
        return None
    return unquote(path.split(marker, 1)[1])


def content_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-env", type=Path, required=True)
    parser.add_argument("--target-env", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_url, source_key, source_bucket = storage_settings(args.source_env)
    target_url, target_key, target_bucket = storage_settings(args.target_env)
    if source_url == target_url:
        raise RuntimeError("원본과 대상 Supabase Storage가 같습니다.")

    source = create_client(source_url, source_key)
    target = create_client(target_url, target_key)
    db = create_engine(database_url(args.target_env), connect_args={"prepare_threshold": None})

    with db.connect() as connection:
        urls = {
            value
            for value in connection.execute(
                text(
                    """
                    SELECT image_url FROM clubs WHERE image_url IS NOT NULL
                    UNION
                    SELECT image_url FROM club_activity_images WHERE image_url IS NOT NULL
                    UNION
                    SELECT jsonb_array_elements_text(COALESCE(activity_images::jsonb, '[]'::jsonb))
                    FROM clubs
                    """
                )
            ).scalars()
            if value and not value.startswith("blob:")
        }

    transferable = [(url, object_path(url, source_bucket)) for url in urls]
    transferable = [(url, path) for url, path in transferable if path]
    print(f"이전 가능한 이미지: {len(transferable)}개")
    if not args.apply:
        print("DRY RUN: Storage와 DB를 변경하지 않았습니다.")
        return

    bucket_ids = {
        bucket.id if hasattr(bucket, "id") else bucket["id"]
        for bucket in target.storage.list_buckets()
    }
    if target_bucket not in bucket_ids:
        target.storage.create_bucket(
            target_bucket,
            options={
                "public": True,
                "file_size_limit": 5 * 1024 * 1024,
                "allowed_mime_types": ["image/jpeg", "image/png", "image/webp", "image/gif"],
            },
        )

    replacements: dict[str, str] = {}
    for old_url, path in transferable:
        contents = source.storage.from_(source_bucket).download(path)
        target.storage.from_(target_bucket).upload(
            path,
            contents,
            {"content-type": content_type(path), "upsert": "true"},
        )
        replacements[old_url] = target.storage.from_(target_bucket).get_public_url(path)

    with db.begin() as connection:
        for old_url, new_url in replacements.items():
            connection.execute(
                text("UPDATE clubs SET image_url=:new WHERE image_url=:old"),
                {"old": old_url, "new": new_url},
            )
            connection.execute(
                text("UPDATE club_activity_images SET image_url=:new WHERE image_url=:old"),
                {"old": old_url, "new": new_url},
            )
            connection.execute(
                text(
                    """
                    UPDATE clubs
                    SET activity_images = (
                        SELECT jsonb_agg(CASE WHEN value = :old THEN :new ELSE value END ORDER BY ordinality)
                        FROM jsonb_array_elements_text(COALESCE(activity_images::jsonb, '[]'::jsonb))
                        WITH ORDINALITY AS images(value, ordinality)
                    )
                    WHERE COALESCE(activity_images::jsonb, '[]'::jsonb) ? :old
                    """
                ),
                {"old": old_url, "new": new_url},
            )
    print(f"이미지 이전 및 URL 교체 완료: {len(replacements)}개")


if __name__ == "__main__":
    main()
