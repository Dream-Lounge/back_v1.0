from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.core.dependencies import get_current_user, require_club_president
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
)
from src.services import application_service, notification_service, club_service
from src.utils.pagination import Page

router = APIRouter(tags=["applications"])


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
    db: Session = Depends(get_db),
    current_user=Depends(require_club_president),
):
    """제출된 신청서 목록 조회 (회장 전용)."""
    return application_service.get_club_applications(
        db, club_id, page, size, q, application_status
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
    db: Session = Depends(get_db),
    current_user=Depends(require_club_president),
):
    """엑셀 생성용 신청서 상세 일괄 조회 (회장 전용)."""
    return application_service.get_club_applications_export(
        db, club_id, page, size, q, application_status
    )


@router.get("/clubs/{club_id}/applications/{application_id}", response_model=AdminApplicationResponse)
def get_club_application(
    club_id: str,
    application_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_president),
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
    current_user=Depends(require_club_president),
):
    """심사 결과 업데이트 — pending(보류) / passed(합격) / failed(불합격) (회장 전용)."""
    try:
        app = application_service.update_application_status(db, club_id, application_id, body.status)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    club = club_service.get_club(db, club_id)
    notification_service.send_application_result(db, app.user_id, club.name, body.status)

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
    current_user=Depends(require_club_president),
):
    """해당 동아리 신청서의 관리자 코멘트를 저장한다 (회장 전용)."""
    try:
        app = application_service.update_application_comment(
            db, club_id, application_id, body.comment
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
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
    }
