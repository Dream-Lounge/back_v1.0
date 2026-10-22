"""보관 기간이 지난 미인증 가입 대기 계정을 정리하는 운영 스크립트."""

from src.db.session import SessionLocal
from src.services.auth_service import cleanup_stale_unverified_users


def main() -> None:
    with SessionLocal() as db:
        count = cleanup_stale_unverified_users(db)
    print(f"deleted_unverified_users={count}")


if __name__ == "__main__":
    main()
