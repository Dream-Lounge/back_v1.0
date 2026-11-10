import calendar
import json
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.core.config import settings
from src.models.application import Application, ApplicationAnswer, ApplicationForm
from src.models.club import Club
from src.models.club_member import ClubMember
from src.models.user import User
from src.schemas.application import (
    ApplicationCreate,
    ApplicationUpdate,
    GuestApplicationCreate,
)
from src.services.audit_service import queue_audit_log
from src.services.recruitment_service import close_expired_recruitments
from src.utils.time import kst_today, utc_now_naive

CLUB_PRESIDENT_APPLICATION_ERROR = "동아리 관리자는 본인 동아리에 신청할 수 없습니다."
RECRUITMENT_CLOSED_ERROR = "모집이 마감된 동아리에는 지원할 수 없습니다."


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _normalized_phone(value: str | None) -> str:
    return "".join(char for char in (value or "") if char.isdigit())


def _ensure_not_club_president(
    db: Session, user_id: str, club_id: str
) -> None:
    membership = (
        db.query(ClubMember)
        .filter(
            ClubMember.club_id == club_id,
            ClubMember.user_id == user_id,
            ClubMember.role.in_(("president", "admin")),
            ClubMember.status == "active",
        )
        .first()
    )
    if membership:
        raise PermissionError(CLUB_PRESIDENT_APPLICATION_ERROR)


def _ensure_club_is_recruiting(db: Session, club_id: str) -> None:
    """관리자 토글과 한국 날짜 범위를 서버에서도 최종 검증한다."""
    close_expired_recruitments(db, club_id=club_id)
    club = db.get(Club, club_id)
    today = kst_today()
    if (
        not club
        or not club.is_recruiting
        or (club.recruit_start is not None and today < club.recruit_start)
        or (club.recruit_end is not None and today > club.recruit_end)
    ):
        raise ValueError(RECRUITMENT_CLOSED_ERROR)


def _to_list_dict(app: Application) -> dict:
    club = app.form.club if app.form else None
    return {
        "id": app.id,
        "form_id": app.form_id,
        "club_id": app.form.club_id if app.form else None,
        "club_name": club.name if club else None,
        "club_image": club.image_url if club else None,
        "club_category": (club.division or club.club_type) if club else None,
        "status": app.status,
        "is_draft": app.is_draft,
        "submitted_at": app.submitted_at,
        "updated_at": app.updated_at,
        "admin_comment": app.admin_comment,
        "applicant_type": app.applicant_type,
    }


def _to_detail_dict(app: Application) -> dict:
    d = _to_list_dict(app)
    snapshot = app.form_snapshot if isinstance(app.form_snapshot, dict) else None
    snapshot_questions = {
        item.get("id"): item
        for item in (snapshot or {}).get("questions", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    enriched_answers = []
    for answer in app.answers:
        snapshot_question = snapshot_questions.get(answer.question_id, {})
        current_question = getattr(answer, "question", None)
        enriched_answers.append({
            "question_id": answer.question_id,
            "answer_text": answer.answer_text,
            "question_text": snapshot_question.get("question_text")
            or getattr(current_question, "question_text", None),
            "question_type": snapshot_question.get("question_type")
            or getattr(current_question, "question_type", None),
            "is_required": snapshot_question.get("is_required")
            if "is_required" in snapshot_question
            else getattr(current_question, "is_required", None),
            "order_index": snapshot_question.get("order_index")
            if "order_index" in snapshot_question
            else getattr(current_question, "order_index", None),
            "options": snapshot_question.get("options")
            if "options" in snapshot_question
            else getattr(current_question, "options", None),
        })
    enriched_answers.sort(key=lambda item: (
        item["order_index"] if item["order_index"] is not None else 10_000,
        item["question_id"],
    ))
    d["answers"] = enriched_answers
    d["form_snapshot"] = snapshot
    d.update({
        "applicant_student_id": app.applicant_student_id,
        "applicant_name": app.applicant_name,
        "applicant_department": app.applicant_department,
        "applicant_phone": app.applicant_phone,
        "applicant_email": app.applicant_email,
        "applicant_grade": app.applicant_grade,
    })
    return d


def _form_snapshot(form: ApplicationForm) -> dict:
    questions = sorted(
        (question for question in form.questions if getattr(question, "is_active", True)),
        key=lambda question: question.order_index,
    )
    return {
        "id": form.id,
        "title": form.title,
        "questions": [
            {
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "is_required": question.is_required,
                "order_index": question.order_index,
                "options": question.options if isinstance(question.options, list) else None,
            }
            for question in questions
        ],
    }


def _validate_answers(form_questions, answers, require_complete: bool) -> None:
    # 삭제된 문항은 기존 제출 내역 보존을 위해 DB에는 남아 있지만,
    # 현재 신청폼의 작성 및 필수 답변 검증 대상에서는 제외한다.
    form_questions = [
        question
        for question in form_questions
        if getattr(question, "is_active", True)
    ]
    question_ids = [a.question_id for a in answers]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("같은 질문에 대한 답변을 중복해서 제출할 수 없습니다.")

    allowed_ids = {q.id for q in form_questions}
    unknown_ids = set(question_ids) - allowed_ids
    if unknown_ids:
        raise ValueError("신청 폼에 속하지 않은 질문이 포함되어 있습니다.")

    if not require_complete:
        return

    answers_by_id = {a.question_id: a.answer_text for a in answers}
    for q in form_questions:
        answer = answers_by_id.get(q.id)
        if q.is_required and (answer is None or not answer.strip()):
            raise ValueError(f"필수 항목에 답변이 누락되었습니다: {q.question_text}")
        if answer is None or not answer.strip():
            continue
        options = q.options if isinstance(q.options, list) else []
        if q.question_type == "choice" and answer not in options:
            raise ValueError(f"허용되지 않은 선택지입니다: {q.question_text}")
        if q.question_type == "multiselect":
            try:
                selected = json.loads(answer)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"복수 선택 답변 형식이 올바르지 않습니다: {q.question_text}") from exc
            if (
                not isinstance(selected, list)
                or any(not isinstance(item, str) for item in selected)
                or len(selected) != len(set(selected))
                or any(item not in options for item in selected)
            ):
                raise ValueError(f"허용되지 않은 복수 선택 답변입니다: {q.question_text}")


def _validate_applicant_info(user: User, data: ApplicationCreate | ApplicationUpdate) -> None:
    if data.applicant_student_id and data.applicant_student_id != user.student_id:
        raise ValueError("가입한 학번과 신청서 학번이 일치하지 않습니다.")
    if data.applicant_name and data.applicant_name.strip() != user.name:
        raise ValueError("가입한 이름과 신청서 이름이 일치하지 않습니다.")


def _applicant_snapshot(user: User, data: ApplicationCreate) -> dict:
    _validate_applicant_info(user, data)
    values = {
        "applicant_student_id": user.student_id,
        "applicant_name": user.name,
        "applicant_department": (data.applicant_department or "").strip() or None,
        "applicant_phone": (data.applicant_phone or "").strip() or None,
        "applicant_grade": (data.applicant_grade or "").strip() or None,
    }
    if not data.is_draft and any(not value for value in values.values()):
        raise ValueError("신청자 기본정보를 모두 입력해주세요.")
    return values


def create_application(db: Session, user: User, data: ApplicationCreate) -> dict:
    form = db.get(ApplicationForm, data.form_id)
    if not form or not form.is_active:
        raise ValueError("존재하지 않거나 비활성화된 신청 폼입니다.")

    _ensure_not_club_president(db, user.id, form.club_id)
    _ensure_club_is_recruiting(db, form.club_id)

    existing_submitted = (
        db.query(Application)
        .filter(
            Application.form_id == data.form_id,
            Application.user_id == user.id,
            Application.is_draft.is_(False),
        )
        .first()
    )
    if existing_submitted:
        raise ValueError("이미 제출한 신청서가 있습니다.")

    existing_draft = db.query(Application).filter(
        Application.form_id == data.form_id,
        Application.user_id == user.id,
        Application.is_draft.is_(True),
    ).first()
    if existing_draft:
        raise ValueError("이미 임시저장한 신청서가 있습니다.")

    if not data.is_draft and not data.privacy_consent:
        raise ValueError("개인정보 수집 및 이용에 동의해주세요.")

    _validate_answers(form.questions, data.answers, require_complete=not data.is_draft)
    applicant_snapshot = _applicant_snapshot(user, data)

    now = utc_now_naive()
    app = Application(
        form_id=data.form_id,
        user_id=user.id,
        is_draft=data.is_draft,
        status="draft" if data.is_draft else "submitted",
        applicant_type="member",
        submitted_at=None if data.is_draft else now,
        form_snapshot=None if data.is_draft else _form_snapshot(form),
        applicant_email=user.email,
        privacy_policy_version=settings.PRIVACY_POLICY_VERSION if not data.is_draft else None,
        privacy_agreed_at=now if not data.is_draft else None,
        **applicant_snapshot,
    )
    try:
        db.add(app)
        db.flush()

        for ans in data.answers:
            db.add(ApplicationAnswer(
                application_id=app.id,
                question_id=ans.question_id,
                answer_text=ans.answer_text,
            ))

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("이미 임시저장하거나 제출한 신청서가 있습니다.") from exc

    result = (
        db.query(Application)
        .options(
            selectinload(Application.answers),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .filter(Application.id == app.id)
        .first()
    )
    return _to_detail_dict(result)


def create_guest_application(db: Session, data: GuestApplicationCreate) -> dict:
    form = db.get(ApplicationForm, data.form_id)
    if not form or not form.is_active:
        raise ValueError("존재하지 않거나 비활성화된 신청 폼입니다.")
    _ensure_club_is_recruiting(db, form.club_id)
    if data.privacy_policy_version != settings.PRIVACY_POLICY_VERSION:
        raise ValueError("최신 개인정보 수집 동의문을 확인해주세요.")
    _validate_answers(form.questions, data.answers, require_complete=True)

    duplicate = db.query(Application.id).filter(
        Application.form_id == form.id,
        Application.applicant_type == "guest",
        Application.applicant_student_id == data.applicant_student_id,
        Application.deleted_at.is_(None),
    ).first()
    if duplicate:
        raise ValueError("이미 제출한 비회원 신청서가 있습니다.")

    now = utc_now_naive()
    app = Application(
        form_id=form.id,
        user_id=None,
        applicant_type="guest",
        status="submitted",
        is_draft=False,
        submitted_at=now,
        applicant_student_id=data.applicant_student_id,
        applicant_name=data.applicant_name,
        applicant_department=data.applicant_department,
        applicant_phone=data.applicant_phone,
        applicant_email=None,
        applicant_grade=data.applicant_grade,
        privacy_policy_version=data.privacy_policy_version,
        privacy_agreed_at=now,
        guest_notice_agreed_at=now,
        form_snapshot=_form_snapshot(form),
    )
    try:
        db.add(app)
        db.flush()
        db.add_all([
            ApplicationAnswer(
                application_id=app.id,
                question_id=answer.question_id,
                answer_text=answer.answer_text,
            )
            for answer in data.answers
        ])
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("이미 제출한 비회원 신청서가 있습니다.") from exc

    result = (
        db.query(Application)
        .options(
            selectinload(Application.answers),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .filter(Application.id == app.id)
        .one()
    )
    return _to_detail_dict(result)


def update_application(
    db: Session, user: User, application_id: str, data: ApplicationUpdate
) -> dict:
    app = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user.id)
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")

    form = db.get(ApplicationForm, app.form_id)
    _ensure_not_club_president(db, user.id, form.club_id)

    if not app.is_draft:
        raise ValueError("이미 제출된 신청서는 수정할 수 없습니다.")

    submitting = data.is_draft is False
    if submitting:
        _ensure_club_is_recruiting(db, form.club_id)
    if submitting and not data.privacy_consent:
        raise ValueError("개인정보 수집 및 이용에 동의해주세요.")
    _validate_applicant_info(user, data)
    # 학번과 이름은 가입 프로필을 원본으로 사용한다. 클라이언트가 값을
    # 생략하거나 변조해도 임시저장·제출 시 프로필 값으로 고정된다.
    app.applicant_student_id = user.student_id
    app.applicant_name = user.name
    snapshot_updates = {
        "applicant_department": data.applicant_department,
        "applicant_phone": data.applicant_phone,
        "applicant_grade": data.applicant_grade,
    }
    for field, value in snapshot_updates.items():
        if value is not None:
            value = value.strip()
            if submitting and not value:
                raise ValueError("신청자 기본정보를 모두 입력해주세요.")
            setattr(app, field, value or None)

    if data.answers is not None:
        _validate_answers(form.questions, data.answers, require_complete=submitting)
        for ans in list(app.answers):
            db.delete(ans)
        db.flush()
        for ans in data.answers:
            db.add(ApplicationAnswer(
                application_id=app.id,
                question_id=ans.question_id,
                answer_text=ans.answer_text,
            ))
        app.updated_at = utc_now_naive()
        db.flush()
        db.refresh(app)

    if submitting:
        if any(
            not getattr(app, field)
            for field in (
                "applicant_student_id",
                "applicant_name",
                "applicant_department",
                "applicant_phone",
                "applicant_grade",
            )
        ):
            raise ValueError("신청자 기본정보를 모두 입력해주세요.")
        answers_to_check = data.answers if data.answers is not None else app.answers
        _validate_answers(form.questions, answers_to_check, require_complete=True)
        app.is_draft = False
        app.status = "submitted"
        app.submitted_at = utc_now_naive()
        app.form_snapshot = _form_snapshot(form)
        app.applicant_email = user.email
        app.privacy_policy_version = settings.PRIVACY_POLICY_VERSION
        app.privacy_agreed_at = utc_now_naive()

    db.commit()

    result = (
        db.query(Application)
        .options(
            selectinload(Application.answers),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .filter(Application.id == app.id)
        .first()
    )
    return _to_detail_dict(result)


def delete_application(db: Session, user: User, application_id: str) -> None:
    """사용자는 임시저장 신청서만 삭제할 수 있다."""
    app = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user.id)
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")
    if not app.is_draft or app.status != "draft":
        raise ValueError("제출된 신청서는 삭제할 수 없습니다. 동아리 관리자에게 문의해주세요.")
    # FK 제약 오류 방지: answers를 먼저 명시 삭제 후 application 삭제
    db.query(ApplicationAnswer).filter(ApplicationAnswer.application_id == app.id).delete(synchronize_session=False)
    db.delete(app)
    db.commit()


def get_draft_applications(db: Session, user: User) -> list[dict]:
    apps = (
        db.query(Application)
        .options(selectinload(Application.form).selectinload(ApplicationForm.club))
        .filter(Application.user_id == user.id, Application.is_draft.is_(True))
        .filter(Application.deleted_at.is_(None))
        .order_by(Application.updated_at.desc())
        .all()
    )
    return [_to_list_dict(app) for app in apps]


def get_draft_application(db: Session, user: User, application_id: str) -> dict | None:
    app = (
        db.query(Application)
        .options(
            selectinload(Application.answers),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .filter(
            Application.id == application_id,
            Application.user_id == user.id,
            Application.is_draft.is_(True),
        )
        .first()
    )
    return _to_detail_dict(app) if app else None


def get_submitted_applications(db: Session, user: User) -> list[dict]:
    apps = (
        db.query(Application)
        .options(selectinload(Application.form).selectinload(ApplicationForm.club))
        .filter(
            or_(
                Application.user_id == user.id,
                Application.linked_user_id == user.id,
            ),
            Application.is_draft.is_(False),
        )
        .filter(Application.deleted_at.is_(None))
        .order_by(Application.submitted_at.desc())
        .all()
    )
    return [_to_list_dict(app) for app in apps]


def get_submitted_application(db: Session, user: User, application_id: str) -> dict | None:
    app = (
        db.query(Application)
        .options(
            selectinload(Application.answers),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .filter(
            Application.id == application_id,
            or_(
                Application.user_id == user.id,
                Application.linked_user_id == user.id,
            ),
            Application.is_draft.is_(False),
            Application.deleted_at.is_(None),
        )
        .first()
    )
    return _to_detail_dict(app) if app else None


def get_active_clubs(db: Session, user: User) -> list[dict]:
    memberships = (
        db.query(ClubMember)
        .join(Club, ClubMember.club_id == Club.id)
        .filter(ClubMember.user_id == user.id, ClubMember.status == "active")
        .all()
    )
    return [
        {
            "club_id": m.club_id,
            "club_name": m.club.name,
            "role": m.role,
            "joined_at": m.joined_at,
        }
        for m in memberships
    ]


# ── 관리자: 신청서 심사 ────────────────────────────────────────────────────────

def _club_applications_query(
    db: Session,
    club_id: str,
    search: str | None = None,
    status_filter: str | None = None,
    applicant_type: str | None = None,
):
    query = (
        db.query(Application)
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            Application.is_draft.is_(False),
            Application.deleted_at.is_(None),
        )
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(
            Application.applicant_name.ilike(pattern),
            Application.applicant_student_id.ilike(pattern),
            Application.applicant_department.ilike(pattern),
        ))
    if status_filter:
        query = query.filter(Application.status == status_filter)
    # 관리자 화면의 회원 구분은 제출 당시 유형이 아니라 현재 계정 연결 상태를 뜻한다.
    # 비회원 신청서가 회원가입 후 연결되면 linked_user_id가 채워지므로 다음 조회부터
    # 회원으로 분류한다. 원본 applicant_type은 감사·이력 보존을 위해 변경하지 않는다.
    if applicant_type == "member":
        query = query.filter(or_(
            Application.user_id.is_not(None),
            Application.linked_user_id.is_not(None),
        ))
    elif applicant_type == "guest":
        query = query.filter(
            Application.user_id.is_(None),
            Application.linked_user_id.is_(None),
        )
    return query


def _current_applicant_type(app: Application) -> str:
    """관리자에게 표시할 현재 회원 상태를 반환한다."""
    return "member" if app.user_id or app.linked_user_id else "guest"


def _to_admin_detail_dict(app: Application) -> dict:
    detail = _to_detail_dict(app)
    return {
        "id": app.id,
        "user_id": app.user_id,
        "user_name": app.applicant_name,
        "user_student_id": app.applicant_student_id,
        "user_department": app.applicant_department,
        "status": app.status,
        "submitted_at": app.submitted_at,
        "admin_comment": app.admin_comment,
        "applicant_department": app.applicant_department,
        "applicant_phone": app.applicant_phone,
        "applicant_email": app.applicant_email,
        "applicant_grade": app.applicant_grade,
        "applicant_type": _current_applicant_type(app),
        "answers": detail["answers"],
        "form_snapshot": detail["form_snapshot"],
    }

def get_club_applications(
    db: Session,
    club_id: str,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    status_filter: str | None = None,
    applicant_type: str | None = None,
) -> dict:
    """동아리에 제출된 신청서 목록 (is_draft=False)."""
    query = _club_applications_query(db, club_id, search, status_filter, applicant_type)
    total = query.count()
    apps = (
        query.order_by(Application.submitted_at.desc(), Application.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    items = [
        {
            "id": a.id,
            "user_id": a.user_id,
            "user_name": a.applicant_name,
            "user_student_id": a.applicant_student_id,
            "user_department": a.applicant_department,
            "status": a.status,
            "submitted_at": a.submitted_at,
            "admin_comment": a.admin_comment,
            "applicant_department": a.applicant_department,
            "applicant_phone": a.applicant_phone,
            "applicant_email": a.applicant_email,
            "applicant_grade": a.applicant_grade,
            "applicant_type": _current_applicant_type(a),
        }
        for a in apps
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


def get_club_applications_export(
    db: Session,
    club_id: str,
    page: int = 1,
    size: int = 100,
    search: str | None = None,
    status_filter: str | None = None,
    applicant_type: str | None = None,
) -> dict:
    """엑셀 생성용 신청자·답변·제출 당시 질문지를 페이지 단위 일괄 조회."""
    query = _club_applications_query(db, club_id, search, status_filter, applicant_type)
    total = query.count()
    applications = (
        query.options(
            selectinload(Application.answers).selectinload(ApplicationAnswer.question),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .order_by(Application.submitted_at.desc(), Application.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "items": [_to_admin_detail_dict(app) for app in applications],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


def get_club_application(db: Session, club_id: str, application_id: str) -> dict | None:
    """동아리 신청서 상세 (관리자용)."""
    app = (
        db.query(Application)
        .options(
            selectinload(Application.answers).selectinload(ApplicationAnswer.question),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            Application.id == application_id,
            Application.is_draft.is_(False),
            Application.deleted_at.is_(None),
        )
        .first()
    )
    if not app:
        return None
    return _to_admin_detail_dict(app)


def update_application_status(
    db: Session,
    club_id: str,
    application_id: str,
    new_status: str,
    *,
    allow_failed_to_pass: bool = False,
) -> Application:
    """심사 결과 업데이트. passed 시 ClubMember 자동 등록."""
    app = (
        db.query(Application)
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            Application.id == application_id,
            Application.is_draft.is_(False),
            Application.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")
    if app.status == "passed":
        raise ValueError("이미 최종 심사가 완료된 신청서입니다.")
    if app.status == "failed" and not (
        allow_failed_to_pass and new_status == "passed"
    ):
        raise ValueError("불합격 신청서는 동아리 회장만 합격으로 변경할 수 있습니다.")

    app.status = new_status

    if new_status == "passed":
        app.accepted_at = utc_now_naive()
        if app.applicant_type == "guest":
            app.link_expires_at = _add_months(app.accepted_at, 4)
            if app.linked_user_id:
                already = db.query(ClubMember).filter(
                    ClubMember.club_id == club_id,
                    ClubMember.user_id == app.linked_user_id,
                    ClubMember.status == "active",
                ).first()
                if not already:
                    db.add(ClubMember(
                        club_id=club_id,
                        user_id=app.linked_user_id,
                        role="member",
                        status="active",
                    ))
        else:
            already = db.query(ClubMember).filter(
                ClubMember.club_id == club_id,
                ClubMember.user_id == app.user_id,
                ClubMember.status == "active",
            ).first()
            if not already:
                db.add(ClubMember(club_id=club_id, user_id=app.user_id, role="member", status="active"))

    db.flush()
    return app


def update_application_comment(
    db: Session, club_id: str, application_id: str, comment: str
) -> Application:
    app = (
        db.query(Application)
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            Application.id == application_id,
            Application.is_draft.is_(False),
            Application.deleted_at.is_(None),
        )
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")
    if app.applicant_type == "guest" and not app.linked_user_id:
        raise ValueError("비회원 신청서에는 관리자 코멘트를 작성할 수 없습니다.")
    app.admin_comment = comment.strip() or None
    db.commit()
    db.refresh(app)
    return app


def soft_delete_application(
    db: Session,
    club_id: str,
    application_id: str,
    actor_user_id: str,
    reason: str,
) -> None:
    app = (
        db.query(Application)
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            Application.id == application_id,
            Application.is_draft.is_(False),
            Application.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")
    app.deleted_at = utc_now_naive()
    app.deleted_by = actor_user_id
    app.deletion_reason = reason.strip()
    queue_audit_log(
        db,
        actor_user_id=actor_user_id,
        action="application.soft_deleted",
        target_type="application",
        target_id=app.id,
        payload={"club_id": club_id, "reason": app.deletion_reason},
    )
    db.commit()


def link_eligible_guest_applications(db: Session, user: User) -> dict:
    if not user.email_verified:
        raise PermissionError("학교 이메일 인증을 완료해주세요.")
    now = utc_now_naive()
    candidates = (
        db.query(Application)
        .options(selectinload(Application.form))
        .filter(
            Application.applicant_type == "guest",
            Application.is_draft.is_(False),
            Application.linked_user_id.is_(None),
            Application.deleted_at.is_(None),
            or_(
                Application.status != "passed",
                Application.link_expires_at >= now,
            ),
            Application.applicant_student_id == user.student_id,
        )
        .order_by(Application.id.asc())
        .with_for_update()
        .all()
    )
    matched = [
        app for app in candidates
        if app.applicant_name.strip() == user.name.strip()
        and _normalized_phone(app.applicant_phone) == _normalized_phone(user.phone)
    ]
    if not matched:
        raise LookupError("연결 가능한 비회원 신청서를 찾을 수 없습니다.")

    linked_ids: list[str] = []
    club_ids: list[str] = []
    for app in matched:
        club_id = app.form.club_id
        if app.status == "passed":
            membership = db.query(ClubMember).filter(
                ClubMember.club_id == club_id,
                ClubMember.user_id == user.id,
            ).with_for_update().first()
            if membership:
                membership.status = "active"
                membership.left_at = None
                if membership.role not in {"president", "admin"}:
                    membership.role = "member"
            else:
                db.add(ClubMember(
                    club_id=club_id,
                    user_id=user.id,
                    role="member",
                    status="active",
                ))
        app.linked_user_id = user.id
        app.linked_at = now
        linked_ids.append(app.id)
        club_ids.append(club_id)
        queue_audit_log(
            db,
            actor_user_id=user.id,
            action="guest_application.linked",
            target_type="application",
            target_id=app.id,
            payload={"club_id": club_id},
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("신청서가 이미 다른 계정에 연결되었습니다.") from exc
    return {
        "linked_application_ids": linked_ids,
        "linked_club_ids": club_ids,
        "linked_count": len(linked_ids),
    }


def record_guest_link_failure(db: Session, user: User, reason: str) -> None:
    """비회원 신청서 연결 실패를 개인정보 없이 운영 감사 기록에 남긴다."""
    queue_audit_log(
        db,
        actor_user_id=user.id,
        action="guest_application.link_failed",
        target_type="user",
        target_id=user.id,
        payload={"reason": reason[:200]},
    )
    db.commit()


def get_applications_for_csv(
    db: Session,
    club_id: str,
    search: str | None = None,
    status_filter: str | None = None,
    applicant_type: str | None = None,
) -> list[dict]:
    query = _club_applications_query(
        db, club_id, search, status_filter, applicant_type
    )
    total = query.count()
    if total > settings.APPLICATION_CSV_MAX_ROWS:
        raise ValueError(
            f"CSV는 한 번에 최대 {settings.APPLICATION_CSV_MAX_ROWS}건까지 다운로드할 수 있습니다."
        )
    applications = (
        query.options(
            selectinload(Application.answers).selectinload(ApplicationAnswer.question),
            selectinload(Application.form).selectinload(ApplicationForm.club),
        )
        .order_by(Application.submitted_at.desc(), Application.id.desc())
        .all()
    )
    return [_to_admin_detail_dict(app) for app in applications]
