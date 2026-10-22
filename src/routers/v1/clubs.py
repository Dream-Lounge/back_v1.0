from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.dependencies import require_club_admin, require_club_manager
from src.db.session import get_db
from src.schemas.club import (
    ApplicationFormResponse,
    ClubCreate,
    ClubResponse,
    ClubUpdate,
    FormCreate,
    FormQuestionResponse,
    FormUpdate,
    QuestionCreate,
    QuestionReorderRequest,
    QuestionUpdate,
)
from src.services import auth_service, club_service
from src.utils.client_ip import get_rate_limit_client_ip
from src.utils.pagination import Page
from src.utils.storage import upload_club_image, upload_pending_club_image

router = APIRouter(prefix="/clubs", tags=["clubs"])

# 모집 상태 변경이 수 분간 남지 않도록 짧게 캐시하고 재검증한다.
PUBLIC_CLUB_CACHE_CONTROL = "public, max-age=5, s-maxage=10, must-revalidate"


class ImageUploadResponse(BaseModel):
    image_url: str


@router.post("/images", response_model=ImageUploadResponse)
async def upload_image_before_club_creation(
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(require_club_admin),
    db: Session = Depends(get_db),
):
    """동아리 생성 전 이미지 업로드 (지정 관리자 전용)."""
    try:
        auth_service.enforce_image_upload_rate_limit(
            db, current_user.id, get_rate_limit_client_ip(request)
        )
        url = await upload_pending_club_image(file, current_user.id)
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="이미지 업로드에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )
    return ImageUploadResponse(image_url=url)


@router.post("/{club_id}/images", response_model=ImageUploadResponse)
async def upload_image(
    club_id: str,
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(require_club_manager),
    db: Session = Depends(get_db),
):
    """동아리 이미지 업로드 (해당 동아리 회장 전용)."""
    try:
        auth_service.enforce_image_upload_rate_limit(
            db, current_user.id, get_rate_limit_client_ip(request)
        )
        url = await upload_club_image(file, club_id)
    except auth_service.RateLimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="이미지 업로드에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )
    return ImageUploadResponse(image_url=url)


@router.get("", response_model=list[ClubResponse])
def list_clubs(
    response: Response,
    search: str | None = Query(default=None, max_length=100),
    is_recruiting: bool | None = Query(default=None),
    division: str | None = Query(default=None, max_length=100),
    field: str | None = Query(default=None, max_length=100),
    atmosphere: str | None = Query(default=None, max_length=100),
    activity_purpose: str | None = Query(default=None, max_length=100),
    tag: list[str] | None = Query(default=None, max_length=20),
    db: Session = Depends(get_db),
):
    """동아리 목록 조회. search 입력 시 동아리 이름 또는 분과로 부분 검색."""
    response.headers["Cache-Control"] = PUBLIC_CLUB_CACHE_CONTROL
    return club_service.get_clubs(
        db,
        search,
        is_recruiting=is_recruiting,
        division=division,
        field=field,
        atmosphere=atmosphere,
        activity_purpose=activity_purpose,
        tags=tag,
    )


@router.get("/page", response_model=Page[ClubResponse])
def list_clubs_page(
    response: Response,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    is_recruiting: bool | None = Query(default=None),
    division: str | None = Query(default=None, max_length=100),
    field: str | None = Query(default=None, max_length=100),
    atmosphere: str | None = Query(default=None, max_length=100),
    activity_purpose: str | None = Query(default=None, max_length=100),
    tag: list[str] | None = Query(default=None, max_length=20),
    db: Session = Depends(get_db),
):
    """필터와 정렬을 적용한 동아리 페이지 조회."""
    response.headers["Cache-Control"] = PUBLIC_CLUB_CACHE_CONTROL
    return club_service.get_clubs_page(
        db,
        page,
        size,
        search,
        is_recruiting=is_recruiting,
        division=division,
        field=field,
        atmosphere=atmosphere,
        activity_purpose=activity_purpose,
        tags=tag,
    )


@router.get("/{club_id}", response_model=ClubResponse)
def get_club(club_id: str, response: Response, db: Session = Depends(get_db)):
    """동아리 상세 조회 (비회원 포함)."""
    club = club_service.get_club(db, club_id)
    if not club:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="동아리를 찾을 수 없습니다.")
    response.headers["Cache-Control"] = PUBLIC_CLUB_CACHE_CONTROL
    return club


@router.get("/{club_id}/form", response_model=ApplicationFormResponse)
def get_club_form(club_id: str, db: Session = Depends(get_db)):
    """동아리 신청 폼(질문 목록) 조회."""
    form = club_service.get_active_form(db, club_id)
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="활성화된 신청 폼이 없습니다.",
        )
    return form


@router.post("", response_model=ClubResponse, status_code=status.HTTP_201_CREATED)
def create_club(
    body: ClubCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_admin),
):
    """동아리 등록 (지정 관리자 전용). 등록 즉시 회장 권한 부여."""
    try:
        return club_service.create_club(db, current_user, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{club_id}", response_model=ClubResponse)
def update_club(
    club_id: str,
    body: ClubUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """동아리 정보 수정 (회장 전용)."""
    club = club_service.get_club(db, club_id)
    if not club:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="동아리를 찾을 수 없습니다.")
    try:
        return club_service.update_club(db, club, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ── 신청 폼 관리 ───────────────────────────────────────────────────────────────

@router.post("/{club_id}/form", response_model=ApplicationFormResponse, status_code=status.HTTP_201_CREATED)
def create_form(
    club_id: str,
    body: FormCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """신청 폼 생성 (회장 전용)."""
    try:
        return club_service.create_form(db, club_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{club_id}/form", response_model=ApplicationFormResponse)
def update_form(
    club_id: str,
    body: FormUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """신청 폼 제목/활성 상태 수정 (회장 전용)."""
    try:
        return club_service.update_form(db, club_id, body)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{club_id}/form/questions", response_model=FormQuestionResponse, status_code=status.HTTP_201_CREATED)
def add_question(
    club_id: str,
    body: QuestionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """질문 추가 (회장 전용)."""
    try:
        return club_service.add_question(db, club_id, body)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/{club_id}/form/questions/{question_id}", response_model=FormQuestionResponse)
def update_question(
    club_id: str,
    question_id: str,
    body: QuestionUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """질문 수정 (회장 전용)."""
    try:
        return club_service.update_question(db, club_id, question_id, body)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{club_id}/form/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    club_id: str,
    question_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """질문 삭제 (회장 전용)."""
    try:
        club_service.delete_question(db, club_id, question_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{club_id}/form/questions/reorder", response_model=ApplicationFormResponse)
def reorder_questions(
    club_id: str,
    body: QuestionReorderRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_club_manager),
):
    """질문 순서 변경 (회장 전용). question_ids에 원하는 순서대로 질문 ID를 담아 보내세요."""
    try:
        return club_service.reorder_questions(db, club_id, body.question_ids)
    except (LookupError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
