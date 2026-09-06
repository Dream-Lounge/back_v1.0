import logging
import resend
from src.core.config import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY


def send_verification_email(to_email: str, code: str) -> None:
    """6자리 인증번호가 포함된 이메일 발송."""
    if not settings.RESEND_API_KEY:
        logger.error("RESEND_API_KEY가 설정되지 않았습니다.")
        raise RuntimeError("이메일 서비스 API 키가 설정되지 않았습니다.")

    try:
        result = resend.Emails.send({
            "from": settings.RESEND_FROM_EMAIL,
            "to": [to_email],
            "subject": "[Dream Lounge] 이메일 인증번호",
            "html": (
                f"<p>안녕하세요!</p>"
                f"<p>Dream Lounge 이메일 인증번호입니다.</p>"
                f"<h2 style='letter-spacing:4px'>{code}</h2>"
                f"<p>인증번호는 {settings.EMAIL_VERIFICATION_EXPIRY_MINUTES}분 동안 유효합니다.</p>"
            ),
        })
        logger.info(f"이메일 발송 성공: to={to_email}, resend_id={result.id}")
    except Exception as e:
        logger.error(f"Resend API 이메일 발송 실패: to={to_email}, error={e}", exc_info=True)
        raise


def send_application_result_email(to_email: str, club_name: str, result_status: str) -> None:
    """신청서 심사 결과(합격/보류/불합격) 이메일 발송."""
    raise NotImplementedError
