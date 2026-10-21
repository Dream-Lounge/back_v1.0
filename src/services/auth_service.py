import hashlib
import hmac
import secrets
import logging
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from supabase_auth.errors import AuthApiError

from src.core.config import settings
from src.core.security import hash_password, verify_password
from src.models.club_member import ClubMember
from src.models.user import User, PrivacyConsent, AuthRateLimit, AuthSession
from src.schemas.user import UserCreate
from src.utils.time import utc_now_naive
from src.utils.supabase_client import (
    create_supabase_auth_client,
    get_supabase_admin_client,
)


logger = logging.getLogger(__name__)
ACTIVE_PRESIDENT_WITHDRAWAL_ERROR = (
    "동아리 회장은 다른 부원에게 회장 권한을 이전한 후 회원탈퇴할 수 있습니다."
)


class RateLimitExceeded(ValueError):
    """요청 횟수 제한 초과."""


def login_lock_message() -> str:
    return (
        f"로그인 {settings.LOGIN_MAX_ATTEMPTS}회 실패하여 "
        f"{settings.LOGIN_LOCK_MINUTES}분 후 다시 시도해주세요!"
    )


def login_ip_rate_limit_message() -> str:
    return "동일 네트워크의 로그인 요청이 너무 많습니다. 잠시 후 다시 시도해주세요."


def _fingerprint(value: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        value.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _supabase_password(user_id: str, pin: str) -> str:
    """사용자 비밀번호를 Supabase Auth용 고강도 내부 비밀번호로 파생한다."""
    return f"Dl1!{_fingerprint(f'supabase-password:{user_id}:{pin}')}"


def _rate_subject(action: str, subject: str) -> str:
    return _fingerprint(f"{action}:{subject}")


def _rate_ip(ip: str | None) -> str | None:
    return _fingerprint(f"ip:{ip}") if ip else None


def _rate_device(device_id: str | None) -> str | None:
    return _fingerprint(f"device:{device_id}") if device_id else None


def _find_auth_user_by_email(email: str):
    admin = get_supabase_admin_client().auth.admin
    for page in range(1, 101):
        users = admin.list_users(page=page, per_page=1000)
        for auth_user in users:
            if auth_user.email and auth_user.email.lower() == email.lower():
                return auth_user
        if len(users) < 1000:
            break
    return None


def _recent_event_count(
    db: Session,
    action: str,
    subject: str,
    since: datetime,
    client_ip: str | None = None,
    device_id: str | None = None,
) -> tuple[int, int, int]:
    subject_hash = _rate_subject(action, subject)
    subject_count = db.query(AuthRateLimit).filter(
        AuthRateLimit.action == action,
        AuthRateLimit.subject_hash == subject_hash,
        AuthRateLimit.created_at >= since,
    ).count()
    ip_count = 0
    ip_hash = _rate_ip(client_ip)
    if ip_hash:
        ip_count = db.query(AuthRateLimit).filter(
            AuthRateLimit.action == action,
            AuthRateLimit.ip_hash == ip_hash,
            AuthRateLimit.created_at >= since,
        ).count()
    device_count = 0
    device_hash = _rate_device(device_id)
    if device_hash:
        device_count = db.query(AuthRateLimit).filter(
            AuthRateLimit.action == action,
            AuthRateLimit.device_hash == device_hash,
            AuthRateLimit.created_at >= since,
        ).count()
    return subject_count, device_count, ip_count


def _record_event(
    db: Session,
    action: str,
    subject: str,
    client_ip: str | None,
    device_id: str | None = None,
) -> None:
    db.add(AuthRateLimit(
        action=action,
        subject_hash=_rate_subject(action, subject),
        ip_hash=_rate_ip(client_ip),
        device_hash=_rate_device(device_id),
    ))


def enforce_login_rate_limit(
    db: Session,
    student_id: str,
    client_ip: str | None = None,
    device_id: str | None = None,
) -> None:
    since = utc_now_naive() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
    subject_count, device_count, ip_count = _recent_event_count(
        db, "login_failure", student_id, since, client_ip, device_id
    )
    user = db.query(User).filter(User.student_id == student_id).first()
    if user and user.locked_until and user.locked_until > utc_now_naive():
        raise RateLimitExceeded(login_lock_message())
    if subject_count >= settings.LOGIN_MAX_ATTEMPTS:
        raise RateLimitExceeded(login_lock_message())
    if device_count >= settings.LOGIN_DEVICE_MAX_ATTEMPTS:
        raise RateLimitExceeded("이 기기의 로그인 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    if ip_count >= settings.LOGIN_NETWORK_MAX_ATTEMPTS:
        raise RateLimitExceeded(login_ip_rate_limit_message())


def record_login_failure(
    db: Session,
    student_id: str,
    client_ip: str | None = None,
    device_id: str | None = None,
) -> str | None:
    user = (
        db.query(User)
        .filter(User.student_id == student_id)
        .with_for_update()
        .first()
    )
    _record_event(db, "login_failure", student_id, client_ip, device_id)
    db.flush()
    since = utc_now_naive() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
    subject_count, device_count, ip_count = _recent_event_count(
        db, "login_failure", student_id, since, client_ip, device_id
    )
    is_locked = subject_count >= settings.LOGIN_MAX_ATTEMPTS
    is_device_limited = device_count >= settings.LOGIN_DEVICE_MAX_ATTEMPTS
    is_ip_limited = ip_count >= settings.LOGIN_NETWORK_MAX_ATTEMPTS
    if user:
        user.failed_login_count = subject_count
        if is_locked:
            user.locked_until = utc_now_naive() + timedelta(
                minutes=settings.LOGIN_LOCK_MINUTES
            )
    db.commit()
    if is_locked:
        return login_lock_message()
    if is_device_limited:
        return "이 기기의 로그인 요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
    if is_ip_limited:
        return login_ip_rate_limit_message()
    return None


def clear_login_failures(db: Session, student_id: str) -> None:
    db.query(AuthRateLimit).filter(
        AuthRateLimit.action == "login_failure",
        AuthRateLimit.subject_hash == _rate_subject("login_failure", student_id),
    ).delete(synchronize_session=False)
    user = db.query(User).filter(User.student_id == student_id).first()
    if user:
        user.failed_login_count = 0
        user.locked_until = None
    db.commit()


def enforce_image_upload_rate_limit(
    db: Session, user_id: str, client_ip: str | None = None
) -> None:
    since = utc_now_naive() - timedelta(hours=1)
    subject_count, _, ip_count = _recent_event_count(
        db, "image_upload", user_id, since, client_ip
    )
    if subject_count >= settings.IMAGE_UPLOAD_MAX_PER_HOUR or ip_count >= 100:
        raise RateLimitExceeded("이미지 업로드 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    _record_event(db, "image_upload", user_id, client_ip)
    db.commit()


def enforce_registration_rate_limit(
    db: Session,
    student_id: str,
    client_ip: str | None = None,
    device_id: str | None = None,
) -> None:
    """회원가입 요청을 학번·브라우저 기기·공인 IP 기준으로 제한한다."""
    since = utc_now_naive() - timedelta(hours=1)
    subject_count, device_count, ip_count = _recent_event_count(
        db, "registration_attempt", student_id, since, client_ip, device_id
    )
    if (
        subject_count >= 5
        or device_count >= settings.REGISTRATION_DEVICE_MAX_PER_HOUR
        or ip_count >= settings.REGISTRATION_NETWORK_MAX_PER_HOUR
    ):
        raise RateLimitExceeded("회원가입 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    _record_event(db, "registration_attempt", student_id, client_ip, device_id)
    db.commit()


def enforce_refresh_rate_limit(
    db: Session,
    device_id: str,
    client_ip: str | None = None,
) -> None:
    """세션 갱신 폭주를 기기 중심으로 제한하고 IP는 넓은 안전망으로 둔다."""
    since = utc_now_naive() - timedelta(minutes=10)
    _, device_count, ip_count = _recent_event_count(
        db, "session_refresh", device_id, since, client_ip, device_id
    )
    if (
        device_count >= settings.REFRESH_DEVICE_MAX_PER_10_MINUTES
        or ip_count >= settings.REFRESH_IP_MAX_PER_10_MINUTES
    ):
        raise RateLimitExceeded("세션 갱신 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    _record_event(db, "session_refresh", device_id, client_ip, device_id)
    db.commit()


def register_user(db: Session, data: UserCreate) -> User:
    """사용자를 만들고 운영 환경에서는 Supabase 확인 메일을 발송한다."""
    normalized_email = str(data.email).strip().lower()
    if db.query(User).filter(User.student_id == data.student_id).first():
        raise ValueError("이미 가입된 회원 정보입니다.")
    if db.query(User).filter(User.email == normalized_email).first():
        raise ValueError("이미 사용 중인 이메일입니다.")

    # 중복 확인으로 열린 읽기 트랜잭션을 먼저 끝낸다. 이후 Supabase Auth
    # 네트워크 호출 동안 SQLAlchemy 풀 연결을 점유하지 않게 한다.
    db.rollback()

    user_id = str(uuid4())
    user = User(
        id=user_id,
        auth_user_id=None,
        student_id=data.student_id,
        password_hash=hash_password(data.password),
        name=data.name,
        phone=None,
        department=None,
        email=normalized_email,
        email_verified=False,
        email_verified_at=None,
    )
    auth_user_id: str | None = None
    try:
        if settings.SUPABASE_SERVICE_KEY and settings.SUPABASE_ANON_KEY:
            internal_password = _supabase_password(user_id, data.password)
            try:
                created = create_supabase_auth_client().auth.sign_up({
                    "email": user.email,
                    "password": internal_password,
                    "options": {
                        "data": {
                            "student_id": user.student_id,
                            "name": user.name,
                        }
                    },
                })
                if not created.user:
                    raise RuntimeError("이메일 인증 계정을 생성하지 못했습니다.")
                if getattr(created.user, "identities", None) == []:
                    # Confirm email이 켜진 Supabase는 계정 열거 방지를 위해
                    # 중복 가입에도 가짜 사용자 객체를 반환할 수 있다.
                    raise ValueError("이미 사용 중인 이메일입니다.")
                # Confirm email이 꺼져 있으면 Supabase가 즉시 세션을 반환한다.
                # 운영에서 인증이 우회되지 않도록 설정 오류로 처리한다.
                if created.session is not None:
                    get_supabase_admin_client().auth.admin.delete_user(
                        str(created.user.id), should_soft_delete=False
                    )
                    raise RuntimeError(
                        "Supabase Authentication에서 Confirm email을 활성화해주세요."
                    )
                auth_user_id = str(created.user.id)
            except AuthApiError as exc:
                if exc.code in {"email_exists", "user_already_exists"}:
                    raise ValueError("이미 사용 중인 이메일입니다.") from exc
                raise

            user.auth_user_id = auth_user_id
        else:
            # 로컬 단위 테스트와 Supabase를 쓰지 않는 개발 환경 전용이다.
            # 운영 설정 검증은 URL/publishable/secret key 누락을 허용하지 않는다.
            user.email_verified = True
            user.email_verified_at = utc_now_naive()
        db.add(user)
        db.commit()
        return user
    except IntegrityError as exc:
        db.rollback()
        if auth_user_id:
            try:
                get_supabase_admin_client().auth.admin.delete_user(auth_user_id)
            except Exception:
                logger.exception("DB 가입 충돌 후 Supabase Auth 계정 정리에 실패했습니다.")
        raise ValueError("이미 가입된 회원 정보입니다.") from exc
    except Exception:
        db.rollback()
        if auth_user_id:
            try:
                get_supabase_admin_client().auth.admin.delete_user(auth_user_id)
            except Exception:
                logger.exception("DB 가입 실패 후 Supabase Auth 계정 정리에 실패했습니다.")
        raise


def requires_email_verification(user: User) -> bool:
    """과거 간소화 계정은 유지하고 실제 이메일 신규 계정만 인증을 요구한다."""
    is_legacy_internal_email = user.email.lower().endswith("@simple.dreamlounge.local")
    return not is_legacy_internal_email and not user.email_verified


def verify_signup_email(db: Session, email: str, token: str) -> User:
    """Supabase OTP를 검증하고 로컬 사용자의 이메일 인증 상태를 동기화한다."""
    normalized_email = email.strip().lower()
    response = create_supabase_auth_client().auth.verify_otp({
        "email": normalized_email,
        "token": token.strip(),
        "type": "email",
    })
    auth_user = response.user
    if not auth_user:
        raise ValueError("인증번호가 올바르지 않거나 만료되었습니다.")

    user = db.query(User).filter(User.email == normalized_email).with_for_update().first()
    if not user or not user.is_active:
        raise ValueError("인증할 회원가입 정보를 찾을 수 없습니다.")
    if user.auth_user_id and user.auth_user_id != str(auth_user.id):
        raise ValueError("인증 계정 정보가 일치하지 않습니다.")

    user.auth_user_id = str(auth_user.id)
    user.email_verified = True
    user.email_verified_at = utc_now_naive()
    db.commit()
    db.refresh(user)
    return user


def resend_signup_email(
    db: Session,
    email: str,
    client_ip: str | None = None,
    device_id: str | None = None,
) -> bool:
    """미인증 가입자에게 확인 메일을 재발송한다. 존재 여부는 호출자에게 숨긴다."""
    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not user.is_active or user.email_verified:
        db.rollback()
        return False

    since = utc_now_naive() - timedelta(seconds=settings.EMAIL_VERIFICATION_RESEND_SECONDS)
    subject_count, device_count, _ = _recent_event_count(
        db,
        "email_resend",
        normalized_email,
        since,
        client_ip,
        device_id,
    )
    if subject_count or device_count:
        db.rollback()
        raise RateLimitExceeded(
            f"인증메일은 {settings.EMAIL_VERIFICATION_RESEND_SECONDS}초 후 다시 요청해주세요."
        )
    db.rollback()

    create_supabase_auth_client().auth.resend({
        "type": "signup",
        "email": normalized_email,
    })
    _record_event(db, "email_resend", normalized_email, client_ip, device_id)
    db.commit()
    return True


def _refresh_token_digest(token: str) -> str:
    return _fingerprint(f"refresh-token:{token}")


def create_local_session(db: Session, user: User) -> str:
    """불투명 refresh token을 만들고 HMAC 해시만 DB에 저장한다."""
    now = utc_now_naive()
    db.query(AuthSession).filter(
        (AuthSession.expires_at <= now) | (AuthSession.revoked_at.is_not(None))
    ).delete(synchronize_session=False)

    active = (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.created_at.desc())
        .all()
    )
    for stale in active[max(settings.MAX_ACTIVE_SESSIONS_PER_USER - 1, 0):]:
        stale.revoked_at = now

    token = secrets.token_urlsafe(48)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_refresh_token_digest(token),
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    return token


def rotate_local_session(db: Session, refresh_token: str) -> tuple[str, User]:
    """refresh token을 한 번만 사용하도록 원자적으로 폐기하고 교체한다."""
    now = utc_now_naive()
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == _refresh_token_digest(refresh_token))
        .with_for_update()
        .first()
    )
    if not session or session.revoked_at is not None or session.expires_at <= now:
        db.rollback()
        raise ValueError("유효하지 않거나 만료된 갱신 토큰입니다.")

    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        session.revoked_at = now
        db.commit()
        raise ValueError("사용자를 찾을 수 없습니다.")

    session.revoked_at = now
    session.last_used_at = now
    replacement = secrets.token_urlsafe(48)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_refresh_token_digest(replacement),
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    return replacement, user


def revoke_local_session(db: Session, user_id: str, refresh_token: str) -> None:
    """전달된 refresh token이 현재 사용자 소유일 때만 해당 세션을 폐기한다."""
    session = (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user_id,
            AuthSession.token_hash == _refresh_token_digest(refresh_token),
            AuthSession.revoked_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if session:
        session.revoked_at = utc_now_naive()
        db.commit()


def authenticate_user(db: Session, student_id: str, password: str) -> User | None:
    """학번 + 비밀번호 검증. 성공 시 User 반환, 실패 시 None."""
    user = db.query(User).filter(User.student_id == student_id).first()
    if not user:
        return None
    # 신규 Supabase 연결 계정도 로컬 비밀번호 해시를 유지해 Auth 비밀번호 연결이
    # 깨졌을 때 본인 확인 후 안전하게 복구할 수 있게 한다.
    if user.password_hash != "!supabase-auth-only" and not verify_password(
        password, user.password_hash
    ):
        return None
    if not user.is_active:
        return None
    return user


def create_supabase_session(db: Session, user: User, password: str):
    """Supabase Auth 세션을 만들고 기존 계정은 최초 로그인 시 안전하게 연결한다."""
    if not settings.SUPABASE_SERVICE_KEY:
        return None

    # 정상적으로 연결된 사용자의 로그인은 아래에서 외부 Auth API를 기다린다.
    # 필요한 스칼라 값은 이미 로드됐으므로 객체를 분리하고 읽기 트랜잭션을
    # 끝내 DB 풀 연결을 다른 요청이 즉시 사용할 수 있게 한다.
    if user.auth_user_id:
        db.expunge(user)
        db.rollback()

    auth_client = create_supabase_auth_client()
    internal_password = _supabase_password(user.id, password)
    try:
        response = auth_client.auth.sign_in_with_password({
            "email": user.email,
            "password": internal_password,
        })
    except AuthApiError as exc:
        if exc.code != "invalid_credentials":
            raise

        # 과거 Supabase Auth 계정이 원래 비밀번호로 연결되어 있으면 한 번만
        # 로그인한 뒤 새 내부 비밀번호로 전환한다.
        if user.auth_user_id:
            # 로컬 비밀번호 검증을 통과한 신규 계정은 내부 비밀번호를 안전하게
            # 재설정할 수 있다. 과거 sentinel 계정은 아래 legacy 검증을 쓴다.
            if user.password_hash != "!supabase-auth-only":
                get_supabase_admin_client().auth.admin.update_user_by_id(
                    str(user.auth_user_id), {"password": internal_password}
                )
                response = auth_client.auth.sign_in_with_password({
                    "email": user.email,
                    "password": internal_password,
                })
                return response.session
            legacy_response = auth_client.auth.sign_in_with_password({
                "email": user.email,
                "password": password,
            })
            get_supabase_admin_client().auth.admin.update_user_by_id(
                str(user.auth_user_id), {"password": internal_password}
            )
            response = auth_client.auth.sign_in_with_password({
                "email": user.email,
                "password": internal_password,
            })
            if not response.session:
                response = legacy_response
            return response.session

        # 이전 DB에서 이관된 사용자는 Auth 계정이 이미 있지만 연결 UUID가
        # 비어 있을 수 있다. 로컬 비밀번호 검증이 끝난 요청에서만 복구한다.
        admin = get_supabase_admin_client().auth.admin
        existing = _find_auth_user_by_email(user.email)
        if existing:
            linked = db.query(User).filter(
                User.auth_user_id == str(existing.id), User.id != user.id
            ).first()
            if linked:
                raise RuntimeError("이미 다른 사용자와 연결된 인증 계정입니다.")
            admin.update_user_by_id(str(existing.id), {"password": internal_password})
            auth_user_id = str(existing.id)
        else:
            created = admin.create_user({
                "email": user.email,
                "password": internal_password,
                "email_confirm": True,
                "app_metadata": {"student_id": user.student_id},
            })
            auth_user_id = str(created.user.id)

        response = auth_client.auth.sign_in_with_password({
            "email": user.email,
            "password": internal_password,
        })
        user.auth_user_id = auth_user_id
        db.commit()

    if not user.auth_user_id and response.user:
        user.auth_user_id = str(response.user.id)
        db.commit()
    return response.session


def refresh_supabase_session(db: Session, refresh_token: str):
    """Supabase refresh token을 새 세션으로 교환하고 로컬 사용자를 확인한다."""
    if not settings.SUPABASE_SERVICE_KEY:
        raise RuntimeError("Supabase Auth가 설정되지 않아 세션을 갱신할 수 없습니다.")

    auth_response = create_supabase_auth_client().auth.refresh_session(refresh_token)
    session = auth_response.session
    auth_user = auth_response.user or (session.user if session else None)
    if not session or not auth_user:
        raise ValueError("유효하지 않은 갱신 토큰입니다.")

    user = db.query(User).filter(
        User.auth_user_id == str(auth_user.id),
        User.is_active.is_(True),
    ).first()
    if not user:
        raise ValueError("사용자를 찾을 수 없습니다.")
    if requires_email_verification(user):
        raise ValueError("이메일 인증을 완료해주세요.")

    return session, user


def revoke_supabase_session(access_token: str) -> None:
    """현재 브라우저 세션의 refresh token을 Supabase Auth에서 폐기한다."""
    if not settings.SUPABASE_SERVICE_KEY:
        return
    get_supabase_admin_client().auth.admin.sign_out(access_token, scope="local")


def withdraw_user(db: Session, user: User) -> None:
    """인증 계정을 삭제하고 개인정보를 익명화해 동일 정보 재가입을 허용한다."""
    active_presidency = db.query(ClubMember).filter(
        ClubMember.user_id == user.id,
        ClubMember.role == "president",
        ClubMember.status == "active",
    ).first()
    if active_presidency:
        raise PermissionError(ACTIVE_PRESIDENT_WITHDRAWAL_ERROR)

    withdrawn_at = utc_now_naive()
    active_memberships = db.query(ClubMember).filter(
        ClubMember.user_id == user.id,
        ClubMember.status == "active",
    ).all()
    for membership in active_memberships:
        membership.status = "withdrawn"
        membership.left_at = withdrawn_at

    original_student_id = user.student_id
    auth_user_id = user.auth_user_id

    # 활동 기록의 외래 키는 유지하되 개인정보와 고유값은 제거한다.
    # 따라서 기존 게시글/지원서는 탈퇴 사용자 기록으로 남고 같은 학번은
    # 새로운 계정에서 다시 사용할 수 있다.
    user.auth_user_id = None
    user.student_id = f"deleted_{user.id.replace('-', '')[:12]}"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.name = "탈퇴한 사용자"
    user.phone = None
    user.department = None
    user.email = f"deleted+{user.id}@invalid.local"
    user.email_verified = False
    user.is_active = False
    user.withdrawn_at = withdrawn_at

    db.query(PrivacyConsent).filter(
        PrivacyConsent.user_id == user.id,
    ).delete(synchronize_session=False)
    db.query(AuthRateLimit).filter(
        AuthRateLimit.subject_hash == _rate_subject("login_failure", original_student_id)
    ).delete(synchronize_session=False)
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(
        synchronize_session=False
    )

    try:
        db.flush()
        if settings.SUPABASE_SERVICE_KEY and auth_user_id:
            get_supabase_admin_client().auth.admin.delete_user(
                auth_user_id,
                should_soft_delete=False,
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("회원탈퇴 처리 중 오류가 발생했습니다.", exc_info=True)
        raise RuntimeError("회원탈퇴 처리에 실패했습니다.") from exc
