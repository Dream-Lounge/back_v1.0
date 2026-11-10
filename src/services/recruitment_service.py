"""한국 날짜를 기준으로 동아리 모집 상태를 동기화한다."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.models.club import Club
from src.utils.time import kst_today, utc_now_naive

INVALID_RECRUITMENT_PERIOD_ERROR = "모집 마감일은 시작일과 같거나 이후여야 합니다."


def validate_recruitment_period(
    recruit_start: date | None,
    recruit_end: date | None,
) -> None:
    if recruit_start is not None and recruit_end is not None and recruit_end < recruit_start:
        raise ValueError(INVALID_RECRUITMENT_PERIOD_ERROR)


def normalized_recruitment_status(
    is_recruiting: bool,
    recruit_end: date | None,
    *,
    today: date | None = None,
) -> bool:
    """종료일 당일까지는 모집 중이며 다음 한국 날짜부터 마감한다."""
    current_date = today or kst_today()
    return bool(
        is_recruiting
        and (recruit_end is None or recruit_end >= current_date)
    )


def close_expired_recruitments(
    db: Session,
    *,
    club_id: str | None = None,
    today: date | None = None,
) -> int:
    """기한이 지난 모집 상태를 DB에도 마감으로 저장한다.

    별도 크론 작업에 의존하지 않고 목록·상세·신청 요청 시 실행한다. 같은
    조건의 동시 요청이 들어와도 ``true -> false`` 단방향 갱신이라 안전하다.
    """
    current_date = today or kst_today()
    query = db.query(Club).filter(
        Club.is_recruiting.is_(True),
        Club.recruit_end.is_not(None),
        Club.recruit_end < current_date,
    )
    if club_id is not None:
        query = query.filter(Club.id == club_id)

    updated = query.update(
        {
            Club.is_recruiting: False,
            Club.updated_at: utc_now_naive(),
        },
        synchronize_session="fetch",
    )
    if updated:
        db.commit()
    return updated
