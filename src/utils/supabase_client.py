import logging
from supabase import create_client, Client
from supabase.client import ClientOptions

from src.core.config import settings

logger = logging.getLogger(__name__)

_admin_client: Client | None = None


def get_supabase_admin_client() -> Client:
    """회원 관리와 Storage에만 사용하는 서버 전용 관리자 클라이언트."""
    global _admin_client
    if not settings.SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY가 설정되지 않았습니다.")

    if _admin_client is None:
        _admin_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY,
            options=ClientOptions(
                auto_refresh_token=False,
                persist_session=False,
            ),
        )
        logger.info("Supabase: 관리자 전용 클라이언트가 생성되었습니다.")
    return _admin_client


def create_supabase_auth_client() -> Client:
    """로그인·사용자 토큰 검증용 클라이언트를 요청별로 새로 생성한다."""
    if not settings.SUPABASE_ANON_KEY:
        raise RuntimeError("SUPABASE_ANON_KEY가 설정되지 않았습니다.")

    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY,
        options=ClientOptions(
            auto_refresh_token=False,
            persist_session=False,
        ),
    )
