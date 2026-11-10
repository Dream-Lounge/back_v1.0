from datetime import date, timedelta

import pytest

from src.services.recruitment_service import (
    normalized_recruitment_status,
    validate_recruitment_period,
)


def test_normalized_status_closes_only_after_end_date():
    today = date(2026, 11, 6)

    assert normalized_recruitment_status(True, today, today=today) is True
    assert (
        normalized_recruitment_status(
            True,
            today - timedelta(days=1),
            today=today,
        )
        is False
    )
    assert normalized_recruitment_status(True, None, today=today) is True
    assert normalized_recruitment_status(False, None, today=today) is False


def test_recruitment_period_rejects_end_before_start():
    with pytest.raises(ValueError, match="모집 마감일"):
        validate_recruitment_period(date(2026, 11, 6), date(2026, 11, 5))
