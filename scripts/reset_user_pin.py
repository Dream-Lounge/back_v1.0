"""관리자가 사용자 PIN을 Supabase Auth와 로컬 프로필에 함께 재설정한다."""

import argparse
from getpass import getpass

from src.core.security import hash_password
from src.db.session import SessionLocal
from src.models.user import User
from src.services.auth_service import _supabase_password
from src.utils.supabase_client import get_supabase_admin_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Dream Lounge 사용자 PIN 재설정")
    parser.add_argument("student_id", help="재설정할 학번")
    args = parser.parse_args()

    pin = getpass("새 숫자 4자리 PIN: ")
    confirmation = getpass("새 PIN 확인: ")
    if pin != confirmation:
        raise SystemExit("PIN 확인 값이 일치하지 않습니다.")
    if len(pin) != 4 or not pin.isdigit():
        raise SystemExit("PIN은 숫자 4자리여야 합니다.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.student_id == args.student_id).first()
        if not user or not user.is_active:
            raise SystemExit("활성 사용자를 찾을 수 없습니다.")
        if not user.auth_user_id:
            raise SystemExit("Supabase Auth에 연결되지 않은 사용자입니다.")

        get_supabase_admin_client().auth.admin.update_user_by_id(
            str(user.auth_user_id),
            {"password": _supabase_password(user.id, pin)},
        )
        user.password_hash = hash_password(pin)
        user.failed_login_count = 0
        user.locked_until = None
        db.commit()
        print(f"{args.student_id} 계정의 PIN을 안전하게 재설정했습니다.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
