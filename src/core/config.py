import json
from urllib.parse import quote, unquote
from typing import List
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from sqlalchemy.engine import make_url

# 환경변수를 수정할 수 없는 회장 온보딩 기간에만 사용하는 코드 스위치다.
# 온보딩 종료 후 False로 바꾸고 재배포한다.
FORCE_SELF_SERVICE_CLUB_ADMIN_OPEN = True


class Settings(BaseSettings):
    DATABASE_URL: str
    # Alembic 전용 관리자 연결. 없으면 개발 호환성을 위해 DATABASE_URL을 사용한다.
    MIGRATION_DATABASE_URL: str | None = None

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    APP_DEBUG: bool = False
    DB_POOL_SIZE: int = 12
    DB_MAX_OVERFLOW: int = 8
    DB_POOL_TIMEOUT_SECONDS: int = 15
    DB_POOL_RECYCLE_SECONDS: int = 300

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    MAX_ACTIVE_SESSIONS_PER_USER: int = 5
    # 동아리 회장 온보딩 기간에만 활성화한다. 활성화 중에는 가입자 모두가
    # 관리자 화면에 접근할 수 있으며, 동아리를 만든 계정은 회장 관계로 보존된다.
    ALLOW_SELF_SERVICE_CLUB_ADMIN: bool = False

    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "club-images"
    SUPABASE_JWKS_CACHE_SECONDS: int = 600

    FRONTEND_URL: str = "http://localhost:5173"
    ALLOWED_ORIGINS: str = '["http://localhost:5173", "http://localhost:3000"]'
    # DigitalOcean처럼 외부 공개 URL에 경로 접두사가 붙는 경우 사용한다.
    # 예: 공개 API가 /back-v1-0/api/v1이면 /back-v1-0
    COOKIE_PATH_PREFIX: str = ""

    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 10
    # 브라우저 기기 쿠키를 주 제한으로 사용하고, 공인 IP는 NAT 환경을 고려해
    # 훨씬 넓은 비정상 트래픽 안전망으로만 사용한다.
    LOGIN_DEVICE_MAX_ATTEMPTS: int = 500
    LOGIN_NETWORK_MAX_ATTEMPTS: int = 5000
    REGISTRATION_DEVICE_MAX_PER_HOUR: int = 500
    REGISTRATION_NETWORK_MAX_PER_HOUR: int = 5000
    REFRESH_DEVICE_MAX_PER_10_MINUTES: int = 60
    REFRESH_IP_MAX_PER_10_MINUTES: int = 5000
    IMAGE_UPLOAD_MAX_PER_HOUR: int = 20
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_PROXY_CIDRS: str = "[]"

    @field_validator("DATABASE_URL", "MIGRATION_DATABASE_URL", mode="before")
    @classmethod
    def use_psycopg3_driver(cls, value):
        if isinstance(value, str) and value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+psycopg://", 1)
        if isinstance(value, str) and "://" in value and "@" in value:
            # ALTER ROLE에 지정한 비밀번호 자체는 그대로 사용하되, 연결 URL
            # 안의 @, # 같은 예약 문자는 percent-encoding 해야 한다.
            scheme, remainder = value.split("://", 1)
            userinfo, host_and_path = remainder.rsplit("@", 1)
            if ":" in userinfo:
                username, password = userinfo.split(":", 1)
                value = (
                    f"{scheme}://{username}:"
                    f"{quote(unquote(password), safe='')}@{host_and_path}"
                )
        return value

    def get_allowed_origins(self) -> List[str]:
        return json.loads(self.ALLOWED_ORIGINS)

    def get_trusted_proxy_cidrs(self) -> List[str]:
        return json.loads(self.TRUSTED_PROXY_CIDRS)

    @field_validator("COOKIE_PATH_PREFIX", mode="before")
    @classmethod
    def normalize_cookie_path_prefix(cls, value):
        prefix = str(value or "").strip()
        if prefix in {"", "/"}:
            return ""
        if not prefix.startswith("/") or any(char in prefix for char in ("?", "#")):
            raise ValueError("COOKIE_PATH_PREFIX는 /로 시작하는 URL 경로여야 합니다.")
        if any(part == ".." for part in prefix.split("/")):
            raise ValueError("COOKIE_PATH_PREFIX에 상위 경로(..)를 사용할 수 없습니다.")
        return prefix.rstrip("/")

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.ENVIRONMENT.lower() != "production":
            return self

        if (
            len(self.SECRET_KEY) < 32
            or self.SECRET_KEY == "your-super-secret-key-change-this-in-production-min-32-chars"
        ):
            raise ValueError("운영 환경에는 임의 생성한 32자 이상의 SECRET_KEY가 필요합니다.")
        if not self.SUPABASE_URL.startswith("https://") or not self.SUPABASE_SERVICE_KEY:
            raise ValueError("운영 환경의 Supabase URL과 service key가 필요합니다.")

        runtime_db_user = (make_url(self.DATABASE_URL).username or "").split(".", 1)[0]
        if runtime_db_user in {"postgres", "supabase_admin"}:
            raise ValueError(
                "운영 DATABASE_URL에는 관리자 계정이 아닌 백엔드 전용 DB 계정이 필요합니다."
            )

        origins = self.get_allowed_origins()
        if not origins or "*" in origins or any(
            not origin.startswith("https://") for origin in origins
        ):
            raise ValueError("운영 ALLOWED_ORIGINS에는 HTTPS 출처만 명시할 수 있습니다.")
        if self.TRUST_PROXY_HEADERS and not self.get_trusted_proxy_cidrs():
            raise ValueError(
                "TRUST_PROXY_HEADERS=true이면 TRUSTED_PROXY_CIDRS를 지정해야 합니다."
            )
        return self

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


def is_self_service_club_admin_open() -> bool:
    """코드 임시 스위치가 켜졌거나 환경변수로 허용한 경우 온보딩을 연다."""
    return FORCE_SELF_SERVICE_CLUB_ADMIN_OPEN or settings.ALLOW_SELF_SERVICE_CLUB_ADMIN
