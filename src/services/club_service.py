from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload, with_loader_criteria
from src.models.club import Club, ClubActivityImage, ClubTag
from src.models.club_member import ClubMember
from src.models.application import ApplicationAnswer, ApplicationForm, FormQuestion
from src.models.user import User
from src.schemas.club import ClubCreate, ClubUpdate, FormCreate, FormUpdate, QuestionCreate, QuestionUpdate


def get_clubs(db: Session, search: str | None = None) -> list[Club]:
    """Return clubs whose name or division partially matches ``search``."""
    query = (
        db.query(Club)
        .options(
            selectinload(Club.tags),
            selectinload(Club.activity_image_records),
        )
    )

    normalized_search = search.strip() if search else ""
    if normalized_search:
        escaped_search = (
            normalized_search
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        query = query.filter(
            or_(
                Club.name.ilike(pattern, escape="\\"),
                Club.division.ilike(pattern, escape="\\"),
            )
        )

    return query.all()


def get_club(db: Session, club_id: str) -> Club | None:
    """club_id로 동아리 상세 정보 조회 (tags 포함)."""
    return (
        db.query(Club)
        .options(selectinload(Club.tags), selectinload(Club.activity_image_records))
        .filter(Club.id == club_id)
        .first()
    )


def get_active_form(db: Session, club_id: str) -> ApplicationForm | None:
    """동아리의 활성 신청 폼과 질문 목록 조회 (is_active=True인 최신 폼)."""
    return (
        db.query(ApplicationForm)
        .options(
            selectinload(ApplicationForm.questions),
            with_loader_criteria(
                FormQuestion,
                FormQuestion.is_active.is_(True),
                include_aliases=True,
            ),
        )
        .filter(ApplicationForm.club_id == club_id, ApplicationForm.is_active == True)
        .first()
    )


def _legacy_contacts(
    contact_links: list[dict],
    fallback_email: str | None = None,
    fallback_phone: str | None = None,
    fallback_url: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Keep legacy single-value contact columns compatible with contact_links."""

    def first_value(link_type: str, fallback: str | None) -> str | None:
        return next(
            (
                str(link["value"]).strip()
                for link in contact_links
                if link.get("type") == link_type and str(link.get("value", "")).strip()
            ),
            fallback,
        )

    return (
        first_value("email", fallback_email),
        first_value("phone", fallback_phone),
        first_value("url", fallback_url),
    )


def _replace_activity_image_records(
    db: Session,
    club: Club,
    images: list[dict],
) -> None:
    """정규화된 사진 행을 교체하고 기존 URL 목록과 순서를 동기화한다."""
    for image in list(club.activity_image_records):
        db.delete(image)
    db.flush()

    for order_index, image in enumerate(images):
        db.add(
            ClubActivityImage(
                club_id=club.id,
                image_url=image["image_url"],
                caption=image.get("caption"),
                order_index=order_index,
            )
        )
    club.activity_images = [image["image_url"] for image in images]


def create_club(db: Session, user: User, data: ClubCreate) -> Club:
    if db.query(Club).filter(Club.name == data.name).first():
        raise ValueError("이미 등록된 동아리 이름입니다.")

    contact_links = [link.model_dump() for link in data.contact_links]
    contact_email, contact_phone, open_chat_url = _legacy_contacts(
        contact_links,
        data.contact_email,
        data.contact_phone,
        data.open_chat_url,
    )

    activity_image_details = (
        [image.model_dump() for image in data.activity_image_details]
        if data.activity_image_details is not None
        else [{"image_url": url, "caption": None} for url in data.activity_images]
    )

    club = Club(
        president_id=user.id,
        name=data.name,
        club_type=data.club_type,
        tagline=data.tagline,
        description=data.description,
        contact_email=contact_email,
        contact_phone=contact_phone,
        open_chat_url=open_chat_url,
        contact_links=contact_links,
        image_url=data.image_url,
        activity_images=[image["image_url"] for image in activity_image_details],
        division=data.division,
        field=data.field,
        atmosphere=data.atmosphere,
        activity_purpose=data.activity_purpose,
        activity_period=data.activity_period,
        recruit_start=data.recruit_start,
        recruit_end=data.recruit_end,
        is_recruiting=data.is_recruiting,
    )
    db.add(club)
    db.flush()
    _replace_activity_image_records(db, club, activity_image_details)

    for tag in data.tags:
        db.add(ClubTag(club_id=club.id, tag_key=tag.tag_key, tag_value=tag.tag_value))

    db.add(ClubMember(club_id=club.id, user_id=user.id, role="president", status="active"))
    # 동아리 등록 직후부터 지원 페이지가 열릴 수 있도록 빈 기본 폼을 만든다.
    # 관리자는 이후 문항을 자유롭게 추가할 수 있다.
    db.add(ApplicationForm(club_id=club.id, title=f"{club.name} 지원서", is_active=True))

    db.commit()
    db.refresh(club)
    return club


def update_club(db: Session, club: Club, data: ClubUpdate) -> Club:
    if data.name is not None and data.name != club.name:
        if db.query(Club).filter(Club.name == data.name).first():
            raise ValueError("이미 등록된 동아리 이름입니다.")

    update_values = data.model_dump(
        exclude_unset=True,
        exclude={"tags", "activity_image_details"},
    )

    if data.activity_image_details is not None:
        activity_image_details = [
            image.model_dump() for image in data.activity_image_details
        ]
        update_values["activity_images"] = [
            image["image_url"] for image in activity_image_details
        ]
    elif "activity_images" in update_values:
        captions_by_url = {
            image.image_url: image.caption for image in club.activity_image_records
        }
        activity_image_details = [
            {"image_url": url, "caption": captions_by_url.get(url)}
            for url in update_values["activity_images"]
        ]
    else:
        activity_image_details = None
    if "contact_links" in update_values:
        contact_links = update_values["contact_links"] or []
        contact_email, contact_phone, open_chat_url = _legacy_contacts(contact_links)
        update_values.update(
            contact_email=contact_email,
            contact_phone=contact_phone,
            open_chat_url=open_chat_url,
        )

    for field, value in update_values.items():
        setattr(club, field, value)

    if activity_image_details is not None:
        _replace_activity_image_records(db, club, activity_image_details)

    if data.tags is not None:
        for tag in list(club.tags):
            db.delete(tag)
        db.flush()
        for tag in data.tags:
            db.add(ClubTag(club_id=club.id, tag_key=tag.tag_key, tag_value=tag.tag_value))

    db.commit()
    db.refresh(club)
    return club


# ── 신청 폼 관리 ───────────────────────────────────────────────────────────────

def create_form(db: Session, club_id: str, data: FormCreate) -> ApplicationForm:
    existing = db.query(ApplicationForm).filter(
        ApplicationForm.club_id == club_id,
        ApplicationForm.is_active == True,
    ).first()
    if existing:
        raise ValueError("이미 활성화된 신청 폼이 존재합니다.")

    form = ApplicationForm(club_id=club_id, title=data.title)
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


def update_form(db: Session, club_id: str, data: FormUpdate) -> ApplicationForm:
    form = db.query(ApplicationForm).filter(
        ApplicationForm.club_id == club_id,
        ApplicationForm.is_active == True,
    ).first()
    if not form:
        raise LookupError("활성화된 신청 폼이 없습니다.")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(form, field, value)

    db.commit()
    db.refresh(form)
    return form


def add_question(db: Session, club_id: str, data: QuestionCreate) -> FormQuestion:
    form = db.query(ApplicationForm).filter(
        ApplicationForm.club_id == club_id,
        ApplicationForm.is_active == True,
    ).first()
    if not form:
        raise LookupError("활성화된 신청 폼이 없습니다.")

    question = FormQuestion(
        form_id=form.id,
        question_text=data.question_text,
        question_type=data.question_type,
        is_required=data.is_required,
        order_index=data.order_index,
        options=data.options,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def update_question(db: Session, club_id: str, question_id: str, data: QuestionUpdate) -> FormQuestion:
    question = (
        db.query(FormQuestion)
        .join(ApplicationForm, FormQuestion.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            FormQuestion.id == question_id,
            FormQuestion.is_active.is_(True),
        )
        .first()
    )
    if not question:
        raise LookupError("질문을 찾을 수 없습니다.")

    updates = data.model_dump(exclude_unset=True)
    final_type = updates.get("question_type", question.question_type)
    final_options = updates.get("options", question.options)
    if final_type in {"choice", "multiselect"}:
        if not final_options or len(final_options) < 2:
            raise ValueError("선택형 질문에는 두 개 이상의 선택지가 필요합니다.")
    elif final_options:
        raise ValueError("단답형과 장문형 질문에는 선택지를 설정할 수 없습니다.")

    for field, value in updates.items():
        setattr(question, field, value)

    db.commit()
    db.refresh(question)
    return question


def delete_question(db: Session, club_id: str, question_id: str) -> None:
    question = (
        db.query(FormQuestion)
        .join(ApplicationForm, FormQuestion.form_id == ApplicationForm.id)
        .filter(
            ApplicationForm.club_id == club_id,
            FormQuestion.id == question_id,
            FormQuestion.is_active.is_(True),
        )
        .first()
    )
    if not question:
        raise LookupError("질문을 찾을 수 없습니다.")

    has_answers = db.query(ApplicationAnswer.id).filter(
        ApplicationAnswer.question_id == question.id
    ).first() is not None
    if has_answers:
        question.is_active = False
    else:
        db.delete(question)
    db.commit()


def reorder_questions(db: Session, club_id: str, question_ids: list[str]) -> ApplicationForm:
    form = db.query(ApplicationForm).filter(
        ApplicationForm.club_id == club_id,
        ApplicationForm.is_active == True,
    ).first()
    if not form:
        raise LookupError("활성화된 신청 폼이 없습니다.")

    active_questions = db.query(FormQuestion).filter(
        FormQuestion.form_id == form.id,
        FormQuestion.is_active.is_(True),
    ).all()
    id_to_question = {q.id: q for q in active_questions}
    for idx, qid in enumerate(question_ids):
        if qid not in id_to_question:
            raise ValueError(f"질문 ID를 찾을 수 없습니다: {qid}")
        id_to_question[qid].order_index = idx

    db.commit()
    db.refresh(form)
    return form
