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


def _fingerprint(value: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        value.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _supabase_password(user_id: str, pin: str) -> str:
    """4자리 PIN을 Supabase Auth용 고강도 내부 비밀번호로 파생한다."""
    return f"Dl1!{_fingerprint(f'supabase-password:{user_id}:{pin}')}"


def _rate_subject(action: str, subject: str) -> str:
    return _fingerprint(f"{action}:{subject}")


def _rate_ip(ip: str | None) -> str | None:
    return _fingerprint(f"ip:{ip}") if ip else None


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
) -> tuple[int, int]:
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
    return subject_count, ip_count


def _record_event(db: Session, action: str, subject: str, client_ip: str | None) -> None:
    db.add(AuthRateLimit(
        action=action,
        subject_hash=_rate_subject(action, subject),
        ip_hash=_rate_ip(client_ip),
    ))


def enforce_login_rate_limit(
    db: Session, student_id: str, client_ip: str | None = None
) -> None:
    since = datetime.utcnow() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
    subject_count, ip_count = _recent_event_count(
        db, "login_failure", student_id, since, client_ip
    )
    user = db.query(User).filter(User.student_id == student_id).first()
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        raise RateLimitExceeded(
            f"로그인 시도가 너무 많습니다. {settings.LOGIN_LOCK_MINUTES}분 후 다시 시도해주세요."
        )
    if (
        subject_count >= settings.LOGIN_MAX_ATTEMPTS
        or ip_count >= settings.LOGIN_IP_MAX_ATTEMPTS
    ):
        raise RateLimitExceeded(
            f"로그인 시도가 너무 많습니다. {settings.LOGIN_LOCK_MINUTES}분 후 다시 시도해주세요."
        )


def record_login_failure(
    db: Session, student_id: str, client_ip: str | None = None
) -> None:
    _record_event(db, "login_failure", student_id, client_ip)
    user = (
        db.query(User)
        .filter(User.student_id == student_id)
        .with_for_update()
        .first()
    )
    if user:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
            user.locked_until = datetime.utcnow() + timedelta(
                minutes=settings.LOGIN_LOCK_MINUTES
            )
    db.commit()


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
    since = datetime.utcnow() - timedelta(hours=1)
    subject_count, ip_count = _recent_event_count(
        db, "image_upload", user_id, since, client_ip
    )
    if subject_count >= settings.IMAGE_UPLOAD_MAX_PER_HOUR or ip_count >= 100:
        raise RateLimitExceeded("이미지 업로드 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    _record_event(db, "image_upload", user_id, client_ip)
    db.commit()


def enforce_registration_rate_limit(
    db: Session, student_id: str, client_ip: str | None = None
) -> None:
    """회원가입 요청을 학번과 IP 기준으로 제한한다."""
    since = datetime.utcnow() - timedelta(hours=1)
    subject_count, ip_count = _recent_event_count(
        db, "registration_attempt", student_id, since, client_ip
    )
    if subject_count >= 5 or ip_count >= settings.REGISTRATION_IP_MAX_PER_HOUR:
        raise RateLimitExceeded("회원가입 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    _record_event(db, "registration_attempt", student_id, client_ip)
    db.commit()


def register_user(db: Session, data: UserCreate) -> User:
    """학번과 4자리 PIN으로 DB 사용자와 Supabase Auth 계정을 생성한다."""
    if db.query(User).filter(User.student_id == data.student_id).first():
        raise ValueError("이미 가입된 회원 정보입니다.")

    # 중복 확인으로 열린 읽기 트랜잭션을 먼저 끝낸다. 이후 Supabase Auth
    # 네트워크 호출 동안 SQLAlchemy 풀 연결을 점유하지 않게 한다.
    db.rollback()

    user_id = str(uuid4())
    user = User(
        id=user_id,
        auth_user_id=None,
        student_id=data.student_id,
        password_hash=hash_password(data.password),
        name=data.student_id,
        phone=None,
        department=None,
        # Supabase Auth의 email/password 공급자를 쓰기 위한 내부 식별자다.
        # 실제 학생 이메일이 아니며 API 응답이나 화면에는 노출하지 않는다.
        email=f"{data.student_id}@simple.dreamlounge.local",
        email_verified=False,
    )
    auth_user_id: str | None = None
    try:
        if settings.SUPABASE_SERVICE_KEY:
            admin = get_supabase_admin_client().auth.admin
            internal_password = _supabase_password(user_id, data.password)
            try:
                created = admin.create_user({
                    "email": user.email,
                    "password": internal_password,
                    "email_confirm": True,
                    "app_metadata": {"student_id": user.student_id},
                })
                auth_user_id = str(created.user.id)
            except AuthApiError as exc:
                # 회원가입마다 Auth 사용자 전체를 순회하지 않는다. Supabase가
                # 원자적으로 판정한 중복 오류 코드만 사용자 오류로 변환한다.
                if exc.code in {"email_exists", "user_already_exists"}:
                    raise ValueError("이미 가입된 인증 계정입니다.") from exc
                raise

            user.auth_user_id = auth_user_id
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


def _refresh_token_digest(token: str) -> str:
    return _fingerprint(f"refresh-token:{token}")


def create_local_session(db: Session, user: User) -> str:
    """불투명 refresh token을 만들고 HMAC 해시만 DB에 저장한다."""
    now = datetime.utcnow()
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
    now = datetime.utcnow()
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
        session.revoked_at = datetime.utcnow()
        db.commit()


def authenticate_user(db: Session, student_id: str, password: str) -> User | None:
    """학번 + 비밀번호 검증. 성공 시 User 반환, 실패 시 None."""
    user = db.query(User).filter(User.student_id == student_id).first()
    if not user:
        return None
    # 신규 Supabase 연결 계정도 로컬 PIN 해시를 유지해 Auth 비밀번호 연결이
    # 깨졌을 때 본인 PIN 확인 후 안전하게 복구할 수 있게 한다.
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
            # 로컬 PIN 검증을 통과한 신규 계정은 내부 비밀번호를 안전하게
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

    withdrawn_at = datetime.utcnow()
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
