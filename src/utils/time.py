from datetime import datetime, timezone
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


def utc_now_naive() -> datetime:
    """기존 TIMESTAMP WITHOUT TIME ZONE 컬럼용 UTC 절대시각."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def kst_today():
    """모집 시작·마감 같은 한국 기준 업무 날짜."""
    return datetime.now(KST).date()
