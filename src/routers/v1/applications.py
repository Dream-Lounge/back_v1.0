from typing import Literal
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from src.models.club import Club
from src.db.session import get_db
from src.core.dependencies import get_current_user, require_club_manager
from src.schemas.application import (
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationResponse,
    ApplicationListItem,
    ActiveClubItem,
    ApplicationStatusUpdate,
    ApplicationCommentUpdate,
    AdminApplicationListItem,
    AdminApplicationResponse,
    GuestApplicationCreate,
    GuestApplicationsLinkResponse,
    ApplicationAdminDeleteRequest,
)
from src.services import application_service, notification_service, auth_service
from src.services.audit_service import queue_audit_log
from src.utils.pagination import Page
from src.utils.client_ip import get_rate_limit_client_ip
from src.utils.device import request_device_id

router = APIRouter(tags=["applications"])


def _csv_cell(value) -> str:
    """Excel/Sheets에서 사용자 입력이 수식으로 실행되지 않도록 보호한다."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.post(
    "/guest/applications",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_guest_application(
    body: GuestApplicationCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """비회원 신청서 제출. 임시저장·수정·조회 기능은 제공하지 않는다."""
    try:
        auth_service.enforce_guest_application_rate_limit(
            db,
            body.applicant_student_id,
            get_rate_limit_client_ip(request),
            request_device_id(request),
        )
        return application_service.create_guest_application(db, body)
    except auth_service.RateLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/applications", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
def create_application(
    body: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """신청서 임시저장(is_draft=true) 또는 제출(is_draft=false)."""
    try:
        return application_service.create_application(db, current_user, body)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/applications/{application_id}", response_model=ApplicationResponse)
def update_application(
    application_id: str,
    body: ApplicationUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """임시저장 신청서 수정 또는 최종 제출."""
    try:
        return application_service.update_application(db, current_user, application_id, body)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """신청서 삭제 또는 지원 취소 (합격·불합격 상태는 불가)."""
    try:
        application_service.delete_application(db, current_user, application_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/me/applications/drafts", response_model=list[ApplicationListItem])
def get_draft_applications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """임시저장함 목록 조회."""
    return application_service.get_draft_applications(db, current_user)


@router.get("/me/applications/drafts/{application_id}", response_model=ApplicationResponse)
def get_draft_application(
    application_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """임시저장 신청서 상세 조회 (수정 가능)."""
    app = application_service.get_draft_application(db, current_user, application_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="임시저장 신청서를 찾을 수 없습니다.")
    return app


@router.get("/me/applications/submitted", response_model=list[ApplicationListItem])
def get_submitted_applications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """제출한 신청서 목록 + 상태 조회."""
    return application_service.get_submitted_applications(db, current_user)


@router.get("/me/applications/submitted/{application_id}", response_model=ApplicationResponse)
def get_submitted_application(
    application_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """제출한 신청서 상세 조회 (읽기 전용)."""
    app = application_service.get_submitted_application(db, current_user, application_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="제출한 신청서를 찾을 수 없습니다.")
    return app


@router.get("/me/clubs", response_model=list[ActiveClubItem])
def get_active_clubs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """활동중인(합격한) 동아리 목록 조회."""
    return application_service.get_active_clubs(db, current_user)


@router.post(
    "/me/applications/link-guest",
    response_model=GuestApplicationsLinkResponse,
)
def link_guest_applications(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """인증된 계정 정보와 일치하는 4개월 이내 비회원 합격 신청서를 연결한다."""
    try:
        return application_service.link_eligible_guest_applications(db, current_user)
    except LookupError as exc:
        application_service.record_guest_link_failure(db, current_user, "eligible_application_not_found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        application_service.record_guest_link_failure(db, current_user, "email_not_verified")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        application_service.record_guest_link_failure(db, current_user, "already_linked_or_conflict")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── 관리자: 신청서 심사 ────────────────────────────────────────────────────────

@router.get("/clubs/{club_id}/applications", response_model=Page[AdminApplicationListItem])
def list_club_applications(
    club_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=100),
    application_status: Literal["passed", "pending", "failed", "submitted"] | None = Query(
        None, alias="status"
    ),
    applicant_type: Literal["member", "guest"] | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """제출된 신청서 목록 조회 (회장 전용)."""
    return application_service.get_club_applications(
        db, club_id, page, size, q, application_status, applicant_type
    )


@router.get(
    "/clubs/{club_id}/applications/export",
    response_model=Page[AdminApplicationResponse],
)
def export_club_applications(
    club_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    q: str | None = Query(None, max_length=100),
    application_status: Literal["passed", "pending", "failed", "submitted"] | None = Query(
        None, alias="status"
    ),
    applicant_type: Literal["member", "guest"] | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """엑셀 생성용 신청서 상세 일괄 조회 (회장 전용)."""
    return application_service.get_club_applications_export(
        db, club_id, page, size, q, application_status, applicant_type
    )


@router.get("/clubs/{club_id}/applications/export.csv")
def export_club_applications_csv(
    club_id: str,
    q: str | None = Query(None, max_length=100),
    application_status: Literal["passed", "pending", "failed", "submitted"] | None = Query(
        None, alias="status"
    ),
    applicant_type: Literal["member", "guest"] | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    try:
        rows = application_service.get_applications_for_csv(
            db, club_id, q, application_status, applicant_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "신청유형", "이름", "학번", "학과", "전화번호", "이메일",
        "지원일시", "상태", "질문과 답변",
    ])
    for row in rows:
        answers = "\n\n".join(
            f"{index}. {answer.get('question_text') or '질문'}\n: {answer.get('answer_text') or ''}"
            for index, answer in enumerate(row["answers"], start=1)
        )
        writer.writerow([_csv_cell(value) for value in [
            row["applicant_type"], row["user_name"], row["user_student_id"],
            row["applicant_department"], row["applicant_phone"],
            row["applicant_email"], row["submitted_at"], row["status"], answers,
        ]])
    queue_audit_log(
        db,
        actor_user_id=current_user.id,
        action="application.csv_exported",
        target_type="club",
        target_id=club_id,
        payload={"count": len(rows), "applicant_type": applicant_type},
    )
    db.commit()
    filename = f"club-{club_id}-applications.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/clubs/{club_id}/applications/{application_id}", response_model=AdminApplicationResponse)
def get_club_application(
    club_id: str,
    application_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """신청서 상세 조회 (회장 전용)."""
    result = application_service.get_club_application(db, club_id, application_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="신청서를 찾을 수 없습니다.")
    return result


@router.patch("/clubs/{club_id}/applications/{application_id}/status", response_model=AdminApplicationListItem)
def update_application_status(
    club_id: str,
    application_id: str,
    body: ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """심사 결과 업데이트 — pending(보류) / passed(합격) / failed(불합격) (회장 전용)."""
    try:
        app = application_service.update_application_status(db, club_id, application_id, body.status)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 상태·회원 등록·알림을 하나의 트랜잭션으로 커밋한다.
    club_name = db.query(Club.name).filter(Club.id == club_id).scalar()
    if app.applicant_type == "member" and app.user_id:
        notification_service.queue_application_result(db, app.user_id, club_name, body.status)
    queue_audit_log(
        db,
        actor_user_id=current_user.id,
        action="application.status_changed",
        target_type="application",
        target_id=app.id,
        payload={"club_id": club_id, "status": body.status},
    )
    db.commit()
    db.refresh(app)

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
        "applicant_type": app.applicant_type,
    }


@router.patch(
    "/clubs/{club_id}/applications/{application_id}/comment",
    response_model=AdminApplicationListItem,
)
def update_application_comment(
    club_id: str,
    application_id: str,
    body: ApplicationCommentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """해당 동아리 신청서의 관리자 코멘트를 저장한다 (회장 전용)."""
    try:
        app = application_service.update_application_comment(
            db, club_id, application_id, body.comment
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
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
        "applicant_type": app.applicant_type,
    }


@router.delete(
    "/clubs/{club_id}/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def admin_delete_application(
    club_id: str,
    application_id: str,
    body: ApplicationAdminDeleteRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    try:
        application_service.soft_delete_application(
            db, club_id, application_id, current_user.id, body.reason
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
