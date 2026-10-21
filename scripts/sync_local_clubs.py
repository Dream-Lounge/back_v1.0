"""Refresh the local demo catalog from Dream Lounge's public clubs API."""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from pathlib import Path

API_URL = "https://dreamlounge.site/back-v1-0/api/v1/clubs"
DB_PATH = Path(__file__).resolve().parents[1] / "local-demo.sqlite3"


def main() -> None:
    with urllib.request.urlopen(API_URL, timeout=30) as response:
        clubs = json.load(response)

    columns = (
        "name",
        "club_type",
        "tagline",
        "description",
        "contact_email",
        "contact_phone",
        "open_chat_url",
        "image_url",
        "division",
        "field",
        "atmosphere",
        "activity_purpose",
        "activity_period",
        "recruit_start",
        "recruit_end",
        "is_recruiting",
    )
    assignments = ", ".join(f"{column} = ?" for column in columns)
    with sqlite3.connect(DB_PATH) as connection:
        for club in clubs:
            values = [club.get(column) for column in columns]
            values[-1] = int(bool(values[-1]))
            connection.execute(
                f"UPDATE clubs SET {assignments}, contact_links = ?, activity_images = ? WHERE id = ?",
                [
                    *values,
                    json.dumps(club.get("contact_links") or [], ensure_ascii=False),
                    json.dumps(club.get("activity_images") or [], ensure_ascii=False),
                    club["id"],
                ],
            )
            connection.execute("DELETE FROM club_tags WHERE club_id = ?", (club["id"],))
            for index, tag in enumerate(club.get("tags") or []):
                if isinstance(tag, dict):
                    key = str(tag.get("tag_key") or tag.get("key") or "tag")
                    value = str(tag.get("tag_value") or tag.get("value") or "")
                else:
                    key, value = "tag", str(tag)
                if value:
                    connection.execute(
                        "INSERT INTO club_tags (id, club_id, tag_key, tag_value) VALUES (?, ?, ?, ?)",
                        (f"local-{club['id']}-{index}", club["id"], key, value),
                    )
    print(f"Synced {len(clubs)} clubs into {DB_PATH}")


if __name__ == "__main__":
    main()
