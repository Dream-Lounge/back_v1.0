from datetime import datetime
import json
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.models.application import Application, ApplicationAnswer, ApplicationForm
from src.models.club import Club
from src.models.club_member import ClubMember
from src.models.user import User
from src.schemas.application import ApplicationCreate, ApplicationUpdate


CLUB_PRESIDENT_APPLICATION_ERROR = "동아리 관리자는 본인 동아리에 신청할 수 없습니다."


def _ensure_not_club_president(
    db: Session, user_id: str, club_id: str
) -> None:
    membership = (
        db.query(ClubMember)
        .filter(
            ClubMember.club_id == club_id,
            ClubMember.user_id == user_id,
            ClubMember.role == "president",
            ClubMember.status == "active",
        )
        .first()
    )
    if membership:
        raise PermissionError(CLUB_PRESIDENT_APPLICATION_ERROR)


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
    }


def _to_detail_dict(app: Application) -> dict:
    d = _to_list_dict(app)
    snapshot = app.form_snapshot if isinstance(app.form_snapshot, dict) else None
    snapshot_questions = {
        item.get("id"): item
        for item in (snapshot or {}).get("questions", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    d["answers"] = [
        {
            "question_id": a.question_id,
            "answer_text": a.answer_text,
            "question_text": snapshot_questions.get(a.question_id, {}).get("question_text"),
            "question_type": snapshot_questions.get(a.question_id, {}).get("question_type"),
            "is_required": snapshot_questions.get(a.question_id, {}).get("is_required"),
            "order_index": snapshot_questions.get(a.question_id, {}).get("order_index"),
            "options": snapshot_questions.get(a.question_id, {}).get("options"),
        }
        for a in app.answers
    ]
    d["form_snapshot"] = snapshot
    d.update({
        "applicant_student_id": app.applicant_student_id,
        "applicant_name": app.applicant_name,
        "applicant_department": app.applicant_department,
        "applicant_phone": app.applicant_phone,
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


def _applicant_snapshot(user: User, data: ApplicationCreate) -> dict:
    _validate_applicant_info(user, data)
    values = {
        "applicant_student_id": user.student_id,
        "applicant_name": (data.applicant_name or "").strip() or None,
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

    existing_submitted = (
        db.query(Application)
        .filter(
            Application.form_id == data.form_id,
            Application.user_id == user.id,
            Application.is_draft == False,
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

    _validate_answers(form.questions, data.answers, require_complete=not data.is_draft)
    applicant_snapshot = _applicant_snapshot(user, data)

    now = datetime.utcnow()
    app = Application(
        form_id=data.form_id,
        user_id=user.id,
        is_draft=data.is_draft,
        status="draft" if data.is_draft else "submitted",
        submitted_at=None if data.is_draft else now,
        form_snapshot=None if data.is_draft else _form_snapshot(form),
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
    _validate_applicant_info(user, data)
    snapshot_updates = {
        "applicant_name": data.applicant_name,
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
        app.updated_at = datetime.utcnow()
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
        app.submitted_at = datetime.utcnow()
        app.form_snapshot = _form_snapshot(form)

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
    """신청서 삭제 (임시저장) 또는 지원 취소 (제출됨·검토중)."""
    app = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user.id)
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")
    if app.status in ("passed", "failed"):
        raise ValueError("이미 심사가 완료된 신청서는 취소할 수 없습니다.")
    # FK 제약 오류 방지: answers를 먼저 명시 삭제 후 application 삭제
    db.query(ApplicationAnswer).filter(ApplicationAnswer.application_id == app.id).delete(synchronize_session=False)
    db.delete(app)
    db.commit()


def get_draft_applications(db: Session, user: User) -> list[dict]:
    apps = (
        db.query(Application)
        .options(selectinload(Application.form).selectinload(ApplicationForm.club))
        .filter(Application.user_id == user.id, Application.is_draft == True)
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
            Application.is_draft == True,
        )
        .first()
    )
    return _to_detail_dict(app) if app else None


def get_submitted_applications(db: Session, user: User) -> list[dict]:
    apps = (
        db.query(Application)
        .options(selectinload(Application.form).selectinload(ApplicationForm.club))
        .filter(Application.user_id == user.id, Application.is_draft == False)
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
            Application.user_id == user.id,
            Application.is_draft == False,
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

def get_club_applications(
    db: Session,
    club_id: str,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> dict:
    """동아리에 제출된 신청서 목록 (is_draft=False)."""
    query = (
        db.query(Application)
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(ApplicationForm.club_id == club_id, Application.is_draft == False)
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(
            Application.applicant_name.ilike(pattern),
            Application.applicant_student_id.ilike(pattern),
            Application.applicant_department.ilike(pattern),
        ))
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
            "applicant_grade": a.applicant_grade,
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


def get_club_application(db: Session, club_id: str, application_id: str) -> dict | None:
    """동아리 신청서 상세 (관리자용)."""
    app = (
        db.query(Application)
        .options(selectinload(Application.answers), selectinload(Application.user))
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            Application.id == application_id,
            Application.is_draft == False,
        )
        .first()
    )
    if not app:
        return None
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
        "applicant_grade": app.applicant_grade,
        "answers": app.answers,
    }


def update_application_status(db: Session, club_id: str, application_id: str, new_status: str) -> Application:
    """심사 결과 업데이트. passed 시 ClubMember 자동 등록."""
    app = (
        db.query(Application)
        .join(ApplicationForm, Application.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            Application.id == application_id,
            Application.is_draft == False,
        )
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")
    if app.status in ("passed", "failed"):
        raise ValueError("이미 최종 심사가 완료된 신청서입니다.")

    app.status = new_status

    if new_status == "passed":
        already = db.query(ClubMember).filter(
            ClubMember.club_id == club_id,
            ClubMember.user_id == app.user_id,
            ClubMember.status == "active",
        ).first()
        if not already:
            db.add(ClubMember(club_id=club_id, user_id=app.user_id, role="member", status="active"))

    db.commit()
    db.refresh(app)
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
        )
        .first()
    )
    if not app:
        raise LookupError("신청서를 찾을 수 없습니다.")
    app.admin_comment = comment.strip() or None
    db.commit()
    db.refresh(app)
    return app
