from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1_000)
    top_k: int = Field(5, ge=1, le=20)
    user_profile: dict[str, Any] | None = None


class RecommendationResult(BaseModel):
    club_id: str
    name: str
    score: float
    matched_constraints: list[str]
    evidence: list[str]
    is_recruiting: bool
    confidence: str = "medium"
    reason: str = ""


class RecommendationResponse(BaseModel):
    query: str
    results: list[RecommendationResult]
    model_info: dict[str, str]


class RecommendationQARequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1_000)
    club_id: str | None = None
    previous_question: str | None = Field(None, max_length=1_000)


class RecommendationQAResponse(BaseModel):
    supported: bool
    answer: str
    club_id: str | None
    evidence: list[str]
    model_info: dict[str, str]
    intent: str = "other"
    confidence: float = 0.0
    suggested_questions: list[str] = Field(default_factory=list)


class RecommendationHealthResponse(BaseModel):
    status: str
    clubs: int
    model_info: dict[str, str]
