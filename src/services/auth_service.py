import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from supabase_auth.errors import AuthApiError

from src.core.config import settings
from src.core.security import (
    create_email_verification_token,
    decode_email_verification_token,
    hash_password,
    verify_password,
)
from src.models.club_member import ClubMember
from src.models.user import (
    AuthRateLimit,
    AuthSession,
    PlatformRole,
    PrivacyConsent,
    User,
    UserInterest,
)
from src.schemas.user import UserCreate, UserInterestsUpdate, UserProfileUpdate
from src.services.audit_service import queue_audit_log
from src.utils.supabase_client import (
    create_supabase_auth_client,
    get_supabase_admin_client,
)
from src.utils.time import utc_now_naive

logger = logging.getLogger(__name__)
ACTIVE_PRESIDENT_WITHDRAWAL_ERROR = (
    "동아리 회장은 다른 부원에게 회장 권한을 이전한 후 회원탈퇴할 수 있습니다."
)


class RateLimitExceeded(ValueError):
    """요청 횟수 제한 초과."""


class RegistrationPersistenceError(RuntimeError):
    """중복이 아닌 회원가입 DB 저장 실패."""


def _registration_integrity_message(exc: IntegrityError) -> str | None:
    """알려진 회원 고유값 충돌만 사용자에게 중복 오류로 안내한다."""
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = str(getattr(diagnostic, "constraint_name", "") or "").lower()
    error_text = f"{constraint_name} {original or exc}".lower()

    if "auth_user_id" in error_text:
        return "이메일 인증 계정이 이미 다른 회원과 연결되어 있습니다."
    if "student_id" in error_text:
        return "이미 가입된 학번입니다."
    if "users_email" in error_text or "email_key" in error_text:
        return "이미 사용 중인 이메일입니다."
    return None


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


def enforce_guest_application_rate_limit(
    db: Session,
    student_id: str,
    client_ip: str | None,
    device_id: str,
) -> None:
    since = utc_now_naive() - timedelta(hours=1)
    _, device_count, ip_count = _recent_event_count(
        db, "guest_application", student_id, since, client_ip, device_id
    )
    if (
        device_count >= settings.GUEST_APPLICATION_DEVICE_MAX_PER_HOUR
        or ip_count >= settings.GUEST_APPLICATION_NETWORK_MAX_PER_HOUR
    ):
        raise RateLimitExceeded("비회원 지원 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    _record_event(db, "guest_application", student_id, client_ip, device_id)
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
    if not data.privacy_consent.required_agreed:
        raise ValueError("필수 개인정보 수집 및 이용에 동의해야 합니다.")
    if data.privacy_consent.policy_version != settings.PRIVACY_POLICY_VERSION:
        raise ValueError("최신 개인정보 수집 동의문을 확인해주세요.")
    if db.query(User).filter(User.student_id == data.student_id).first():
        raise ValueError("이미 가입된 학번입니다.")
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
        phone=data.phone,
        department=data.department,
        email=normalized_email,
        email_verified=False,
        email_verified_at=None,
    )
    auth_user_id: str | None = None
    auth_user_created_here = False
    try:
        if settings.SUPABASE_SERVICE_KEY and settings.SUPABASE_ANON_KEY:
            internal_password = _supabase_password(user_id, data.password)
            if data.email_verification_token:
                verified_email, auth_user_id = decode_email_verification_token(
                    data.email_verification_token
                )
                if verified_email != normalized_email:
                    raise ValueError("인증한 이메일과 회원가입 이메일이 일치하지 않습니다.")
                auth_user = get_supabase_admin_client().auth.admin.get_user_by_id(
                    auth_user_id
                ).user
                if not auth_user or str(auth_user.email or "").lower() != normalized_email:
                    raise ValueError("인증한 이메일 계정을 찾을 수 없습니다.")
                get_supabase_admin_client().auth.admin.update_user_by_id(
                    auth_user_id,
                    {
                        "password": internal_password,
                        "user_metadata": {
                            "student_id": user.student_id,
                            "name": user.name,
                        },
                    },
                )
                user.email_verified = True
                user.email_verified_at = utc_now_naive()
            else:
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
                        raise ValueError("이미 사용 중인 이메일입니다.")
                    if created.session is not None:
                        get_supabase_admin_client().auth.admin.delete_user(
                            str(created.user.id), should_soft_delete=False
                        )
                        raise RuntimeError(
                            "Supabase Authentication에서 Confirm email을 활성화해주세요."
                        )
                    auth_user_id = str(created.user.id)
                    auth_user_created_here = True
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
        # audit_logs와 privacy_consents가 users를 FK로 참조한다. SQLAlchemy가
        # 서로 독립된 모델의 INSERT 순서를 추론하도록 두지 말고 부모 행을
        # 먼저 확정해 PostgreSQL의 즉시 FK 검사를 항상 통과시킨다.
        db.flush()
        db.add(
            PrivacyConsent(
                user_id=user.id,
                required_agreed=True,
                optional_agreed=data.privacy_consent.optional_agreed,
                policy_version=data.privacy_consent.policy_version,
            )
        )
        queue_audit_log(
            db,
            actor_user_id=user.id,
            action="user.registered",
            target_type="user",
            target_id=user.id,
            payload={"policy_version": data.privacy_consent.policy_version},
        )
        db.commit()
        return user
    except IntegrityError as exc:
        db.rollback()
        if auth_user_id and auth_user_created_here:
            try:
                get_supabase_admin_client().auth.admin.delete_user(auth_user_id)
            except Exception:
                logger.exception("DB 가입 충돌 후 Supabase Auth 계정 정리에 실패했습니다.")
        message = _registration_integrity_message(exc)
        if message:
            raise ValueError(message) from exc
        logger.exception("중복이 아닌 회원가입 DB 저장 오류가 발생했습니다.")
        raise RegistrationPersistenceError(
            "회원가입 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        ) from exc
    except Exception:
        db.rollback()
        if auth_user_id and auth_user_created_here:
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


def request_signup_email_otp(
    db: Session,
    email: str,
    client_ip: str | None = None,
    device_id: str | None = None,
) -> None:
    """회원정보를 받기 전에 Supabase SMTP를 통해 이메일 OTP만 발송한다."""
    normalized_email = email.strip().lower()
    if db.query(User).filter(User.email == normalized_email).first():
        raise ValueError("이미 사용 중인 이메일입니다.")
    since = utc_now_naive() - timedelta(seconds=settings.EMAIL_VERIFICATION_RESEND_SECONDS)
    subject_count, device_count, _ = _recent_event_count(
        db, "signup_email_otp", normalized_email, since, client_ip, device_id
    )
    if subject_count or device_count:
        db.rollback()
        raise RateLimitExceeded(
            f"인증번호는 {settings.EMAIL_VERIFICATION_RESEND_SECONDS}초 후 다시 요청해주세요."
        )
    db.rollback()
    create_supabase_auth_client().auth.sign_in_with_otp({
        "email": normalized_email,
        "options": {"should_create_user": True},
    })
    _record_event(db, "signup_email_otp", normalized_email, client_ip, device_id)
    db.commit()


def verify_preregistration_email(db: Session, email: str, token: str) -> str:
    """가입 전 OTP를 확인하고 15분간 유효한 서버 서명 증명을 발급한다."""
    normalized_email = email.strip().lower()
    if db.query(User).filter(User.email == normalized_email).first():
        raise ValueError("이미 사용 중인 이메일입니다.")
    db.rollback()
    response = create_supabase_auth_client().auth.verify_otp({
        "email": normalized_email,
        "token": token.strip(),
        "type": "email",
    })
    auth_user = response.user
    if not auth_user:
        raise ValueError("인증번호가 올바르지 않거나 만료되었습니다.")
    return create_email_verification_token(normalized_email, str(auth_user.id))


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


def update_profile(db: Session, user: User, data: UserProfileUpdate) -> User:
    """학번은 고정하고 이름·학과·전화번호를 변경한다."""
    changed: list[str] = []
    for field, value in data.model_dump(exclude_unset=True).items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    if changed:
        queue_audit_log(
            db,
            actor_user_id=user.id,
            action="user.profile_updated",
            target_type="user",
            target_id=user.id,
            payload={"fields": changed},
        )
        db.commit()
        db.refresh(user)
    return user


def replace_interests(db: Session, user: User, data: UserInterestsUpdate) -> list[UserInterest]:
    """관심분야 전체를 한 트랜잭션으로 교체하고 최초 설정 완료 시각을 기록한다."""
    db.query(UserInterest).filter(UserInterest.user_id == user.id).delete(
        synchronize_session=False
    )
    interests = [
        UserInterest(user_id=user.id, tag_key=item.tag_key, tag_value=item.tag_value)
        for item in data.interests
    ]
    db.add_all(interests)
    if data.complete_onboarding and user.onboarding_completed_at is None:
        user.onboarding_completed_at = utc_now_naive()
    queue_audit_log(
        db,
        actor_user_id=user.id,
        action="user.interests_updated",
        target_type="user",
        target_id=user.id,
        payload={"count": len(interests)},
    )
    db.commit()
    return interests


def get_interests(db: Session, user_id: str) -> list[UserInterest]:
    return (
        db.query(UserInterest)
        .filter(UserInterest.user_id == user_id)
        .order_by(UserInterest.tag_key.asc(), UserInterest.tag_value.asc())
        .all()
    )


def get_active_platform_roles(db: Session, user_id: str) -> list[str]:
    return [
        row.role
        for row in db.query(PlatformRole.role)
        .filter(PlatformRole.user_id == user_id, PlatformRole.revoked_at.is_(None))
        .order_by(PlatformRole.role.asc())
        .all()
    ]


def mark_guide_seen(db: Session, user: User) -> User:
    if user.guide_seen_at is None:
        user.guide_seen_at = utc_now_naive()
        db.commit()
        db.refresh(user)
    return user


def hide_guide_today(db: Session, user: User) -> User:
    from src.utils.time import next_kst_midnight_utc_naive

    user.guide_hidden_until = next_kst_midnight_utc_naive()
    db.commit()
    db.refresh(user)
    return user


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise ValueError("현재 비밀번호가 올바르지 않습니다.")
    if current_password == new_password:
        raise ValueError("새 비밀번호는 현재 비밀번호와 달라야 합니다.")

    admin = None
    auth_user_id = str(user.auth_user_id) if user.auth_user_id else None
    old_internal_password = None
    supabase_password_changed = False

    if settings.SUPABASE_SERVICE_KEY and auth_user_id:
        admin = get_supabase_admin_client().auth.admin
        old_internal_password = _supabase_password(user.id, current_password)
        internal_password = _supabase_password(user.id, new_password)
        admin.update_user_by_id(auth_user_id, {"password": internal_password})
        # Supabase는 비밀번호 변경 시 기존 세션을 종료한다. 변경된 비밀번호로
        # 이미 무효화된 access token을 sign_out에 다시 전달하면 403이 발생한다.
        supabase_password_changed = True

    try:
        user.password_hash = hash_password(new_password)
        user.password_changed_at = utc_now_naive()
        db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(
            synchronize_session=False
        )
        queue_audit_log(
            db,
            actor_user_id=user.id,
            action="user.password_changed",
            target_type="user",
            target_id=user.id,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if supabase_password_changed and admin and auth_user_id and old_internal_password:
            try:
                # 외부 Auth만 새 비밀번호가 되는 부분 성공을 방지한다.
                admin.update_user_by_id(
                    auth_user_id, {"password": old_internal_password}
                )
            except Exception as restore_exc:
                logger.critical(
                    "비밀번호 변경 DB 실패 후 Supabase Auth 복구도 실패: user_id=%s error=%s",
                    user.id,
                    restore_exc,
                    exc_info=True,
                )
                raise RuntimeError(
                    "비밀번호 변경 상태를 복구할 수 없습니다. 관리자에게 문의해주세요."
                ) from exc
        raise RuntimeError("비밀번호 변경을 완료하지 못했습니다.") from exc


def request_email_change(
    db: Session,
    user: User,
    *,
    new_email: str,
    access_token: str,
    refresh_token: str,
) -> None:
    """Supabase의 인증된 사용자 이메일 변경 흐름을 시작한다."""
    normalized = new_email.strip().lower()
    if normalized == user.email:
        raise ValueError("현재 이메일과 동일합니다.")
    duplicate = db.query(User.id).filter(
        (User.email == normalized) | (User.pending_email == normalized)
    ).first()
    if duplicate:
        raise ValueError("이미 사용 중인 이메일입니다.")
    if not user.auth_user_id:
        raise RuntimeError("이메일 인증 계정이 연결되어 있지 않습니다.")

    # update_user는 현재 사용자의 세션을 요구하며 이메일 변경 확인 메일을
    # Supabase SMTP 설정을 통해 전송한다.
    auth = create_supabase_auth_client().auth
    auth.set_session(access_token, refresh_token)
    auth.update_user({"email": normalized})

    user.pending_email = normalized
    queue_audit_log(
        db,
        actor_user_id=user.id,
        action="user.email_change_requested",
        target_type="user",
        target_id=user.id,
    )
    db.commit()


def verify_email_change(db: Session, new_email: str, token: str) -> User:
    normalized = new_email.strip().lower()
    response = create_supabase_auth_client().auth.verify_otp({
        "email": normalized,
        "token": token.strip(),
        "type": "email_change",
    })
    auth_user = response.user
    if not auth_user:
        raise ValueError("인증번호가 올바르지 않거나 만료되었습니다.")

    user = (
        db.query(User)
        .filter(User.auth_user_id == str(auth_user.id), User.pending_email == normalized)
        .with_for_update()
        .first()
    )
    if not user or not user.is_active:
        raise ValueError("이메일 변경 요청을 찾을 수 없습니다.")
    user.email = normalized
    user.pending_email = None
    user.email_verified = True
    user.email_verified_at = utc_now_naive()
    queue_audit_log(
        db,
        actor_user_id=user.id,
        action="user.email_changed",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    db.refresh(user)
    return user


def cleanup_stale_unverified_users(db: Session, limit: int = 100) -> int:
    """보관 기간이 지난 미인증 가입 대기 계정을 제한된 수만큼 정리한다."""
    cutoff = utc_now_naive() - timedelta(days=settings.UNVERIFIED_ACCOUNT_RETENTION_DAYS)
    users = (
        db.query(User)
        .filter(
            User.email_verified.is_(False),
            User.is_active.is_(True),
            User.created_at < cutoff,
        )
        .order_by(User.created_at.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    deleted = 0
    for stale in users:
        auth_user_id = stale.auth_user_id
        if settings.SUPABASE_SERVICE_KEY and auth_user_id:
            try:
                get_supabase_admin_client().auth.admin.delete_user(
                    auth_user_id, should_soft_delete=False
                )
            except Exception:
                logger.exception("미인증 Supabase Auth 계정 정리에 실패했습니다: %s", stale.id)
                continue
        db.query(PrivacyConsent).filter(PrivacyConsent.user_id == stale.id).delete(
            synchronize_session=False
        )
        db.query(AuthSession).filter(AuthSession.user_id == stale.id).delete(
            synchronize_session=False
        )
        db.query(UserInterest).filter(UserInterest.user_id == stale.id).delete(
            synchronize_session=False
        )
        db.delete(stale)
        deleted += 1
    db.commit()
    return deleted


def _auth_created_at(value) -> datetime | None:
    """Supabase Auth 사용자 생성 시각을 naive UTC datetime으로 정규화한다."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def cleanup_orphan_supabase_auth_users(db: Session, limit: int | None = None) -> int:
    """로컬 회원이 없는 오래된 가입 중단 Supabase Auth 계정을 정리한다.

    OTP 발송 시 만들어졌지만 최종 회원가입을 완료하지 않은 Auth 사용자만
    대상으로 한다. Auth ID와 이메일 중 하나라도 로컬 사용자와 연결돼 있으면
    삭제하지 않는다.
    """
    if not settings.SUPABASE_SERVICE_KEY:
        return 0

    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        # 두 컨테이너 중 하나만 수행한다. 트랜잭션 종료 시 자동 해제된다.
        acquired = db.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
            {"lock_id": 4_483_141_030_001},
        ).scalar()
        if not acquired:
            db.rollback()
            return 0

    batch_size = max(
        1,
        min(limit or settings.AUTH_ORPHAN_CLEANUP_BATCH_SIZE, 500),
    )
    cutoff = utc_now_naive() - timedelta(days=settings.UNVERIFIED_ACCOUNT_RETENTION_DAYS)
    local_identities = db.query(User.auth_user_id, User.email).all()
    local_auth_ids = {str(auth_id) for auth_id, _ in local_identities if auth_id}
    local_emails = {str(email).strip().lower() for _, email in local_identities if email}
    allowed_domains = set(settings.get_student_email_domains())
    admin = get_supabase_admin_client().auth.admin
    deleted = 0

    try:
        for page in range(1, 101):
            auth_users = admin.list_users(page=page, per_page=1000)
            for auth_user in auth_users:
                auth_user_id = str(getattr(auth_user, "id", "") or "")
                email = str(getattr(auth_user, "email", "") or "").strip().lower()
                activity_times = [
                    value
                    for value in (
                        _auth_created_at(getattr(auth_user, "created_at", None)),
                        _auth_created_at(getattr(auth_user, "updated_at", None)),
                        _auth_created_at(getattr(auth_user, "last_sign_in_at", None)),
                    )
                    if value is not None
                ]
                last_activity_at = max(activity_times) if activity_times else None
                domain = email.rsplit("@", 1)[-1] if "@" in email else ""
                if (
                    not auth_user_id
                    or not email
                    or domain not in allowed_domains
                    or auth_user_id in local_auth_ids
                    or email in local_emails
                    or last_activity_at is None
                    or last_activity_at >= cutoff
                ):
                    continue
                try:
                    admin.delete_user(auth_user_id, should_soft_delete=False)
                except Exception:
                    logger.exception("가입 중단 Supabase Auth 계정 정리에 실패했습니다.")
                    continue
                deleted += 1
                if deleted >= batch_size:
                    db.commit()
                    return deleted
            if len(auth_users) < 1000:
                break
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        raise


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


def withdraw_user(db: Session, user: User, access_token: str | None = None) -> None:
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
    # department는 신규 가입부터 필수/NOT NULL이므로 탈퇴 처리에서도
    # 개인정보를 제거한 비식별 값으로 유지한다.
    user.department = "탈퇴"
    user.email = f"deleted+{user.id}@invalid.local"
    user.email_verified = False
    user.is_active = False
    user.withdrawn_at = withdrawn_at

    db.query(PrivacyConsent).filter(
        PrivacyConsent.user_id == user.id,
    ).delete(synchronize_session=False)
    db.query(UserInterest).filter(UserInterest.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(AuthRateLimit).filter(
        AuthRateLimit.subject_hash == _rate_subject("login_failure", original_student_id)
    ).delete(synchronize_session=False)
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(
        synchronize_session=False
    )

    try:
        queue_audit_log(
            db,
            actor_user_id=user.id,
            action="user.withdrawn",
            target_type="user",
            target_id=user.id,
        )
        db.flush()
        if settings.SUPABASE_SERVICE_KEY and auth_user_id:
            if access_token:
                get_supabase_admin_client().auth.admin.sign_out(
                    access_token, scope="global"
                )
            get_supabase_admin_client().auth.admin.delete_user(
                auth_user_id,
                should_soft_delete=False,
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("회원탈퇴 처리 중 오류가 발생했습니다.")
        raise RuntimeError("회원탈퇴 처리에 실패했습니다.") from exc
