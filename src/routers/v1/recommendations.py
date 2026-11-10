from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.core.dependencies import get_current_user
from src.db.session import get_db
from src.models.user import UserInterest
from src.schemas.recommendation import (
    RecommendationHealthResponse,
    RecommendationQARequest,
    RecommendationQAResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from src.services.qa_answer_service import QaAnswerService
from src.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=RecommendationResponse)
def recommend(payload: RecommendationRequest, db: DatabaseSession):
    return RecommendationService(db).recommend(payload.query, payload.top_k, payload.user_profile)


@router.post("/personalized", response_model=RecommendationResponse)
def personalized_recommend(
    payload: RecommendationRequest,
    db: DatabaseSession,
    current_user=Depends(get_current_user),
):
    """저장된 관심분야를 요청 검색어에 결합한 로그인 사용자 추천."""
    interests = db.query(UserInterest).filter(
        UserInterest.user_id == current_user.id
    ).all()
    stored_profile: dict[str, list[str]] = {}
    for interest in interests:
        stored_profile.setdefault(interest.tag_key, []).append(interest.tag_value)
    if payload.user_profile:
        for key, value in payload.user_profile.items():
            values = value if isinstance(value, list) else [value]
            stored_profile.setdefault(key, []).extend(str(item) for item in values)
    return RecommendationService(db).recommend(
        payload.query,
        payload.top_k,
        stored_profile,
    )


@router.post("/qa", response_model=RecommendationQAResponse)
def answer_question(payload: RecommendationQARequest, db: DatabaseSession):
    try:
        return QaAnswerService(db).answer(
            payload.question,
            payload.club_id,
            payload.previous_question,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/health", response_model=RecommendationHealthResponse)
def recommendation_health(db: DatabaseSession):
    service = RecommendationService(db)
    return {
        "status": "ready" if service.records else "empty",
        "clubs": len(service.records),
        "model_info": service.model_info,
        "llm": QaAnswerService(db).public_status(),
    }
