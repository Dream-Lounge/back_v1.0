from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.schemas.recommendation import (
    RecommendationHealthResponse,
    RecommendationQARequest,
    RecommendationQAResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from src.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=RecommendationResponse)
def recommend(payload: RecommendationRequest, db: DatabaseSession):
    return RecommendationService(db).recommend(payload.query, payload.top_k, payload.user_profile)


@router.post("/qa", response_model=RecommendationQAResponse)
def answer_question(payload: RecommendationQARequest, db: DatabaseSession):
    try:
        return RecommendationService(db).qa(
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
    }
