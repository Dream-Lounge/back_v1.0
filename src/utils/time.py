from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


def utc_now_naive() -> datetime:
    """기존 TIMESTAMP WITHOUT TIME ZONE 컬럼용 UTC 절대시각."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def kst_today():
    """모집 시작·마감 같은 한국 기준 업무 날짜."""
    return datetime.now(KST).date()


def next_kst_midnight_utc_naive() -> datetime:
    """한국시간 기준 다음 날 00:00을 UTC naive 값으로 반환한다."""
    tomorrow = datetime.now(KST).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=KST).astimezone(timezone.utc).replace(tzinfo=None)
