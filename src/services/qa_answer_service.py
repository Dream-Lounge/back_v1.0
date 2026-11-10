"""기존 근거 검색과 선택적 LLM 자연어 답변을 결합한다."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.club import Club
from src.services.llm_client import LlmClient, get_llm_client
from src.services.recommendation_service import RecommendationService


class QaAnswerService:
    def __init__(self, db: Session, llm_client: LlmClient | None = None) -> None:
        self.db = db
        self.llm = llm_client or get_llm_client()

    def answer(
        self,
        question: str,
        club_id: str | None = None,
        previous_question: str | None = None,
    ) -> dict[str, Any]:
        result = RecommendationService(self.db).qa(
            question,
            club_id,
            previous_question,
        )
        return self._enrich_with_llm(result, question)

    def public_status(self) -> dict[str, Any]:
        status = self.llm.status()
        # 내부 LLM 주소와 상세 장애 원인은 공개 API 응답에 포함하지 않는다.
        return {
            "enabled": status.enabled,
            "available": status.available,
            "model": status.model,
        }

    def _enrich_with_llm(
        self,
        result: dict[str, Any],
        question: str,
    ) -> dict[str, Any]:
        result["answer_source"] = "evidence"
        if not result.get("supported") or not result.get("answer"):
            return result
        if not self.llm.configured or not self.llm.available():
            return result

        evidence = (result.get("evidence") or [])[
            : max(1, settings.LLM_TOP_K_EVIDENCE)
        ]
        if not evidence:
            return result

        club_name = ""
        result_club_id = result.get("club_id")
        if result_club_id:
            club = self.db.get(Club, result_club_id)
            if club:
                club_name = club.name or ""

        llm_answer = self.llm.generate_answer(question, club_name, evidence)
        if not llm_answer:
            return result

        result["answer"] = llm_answer
        result["answer_source"] = "llm"
        result["model_info"] = {
            **(result.get("model_info") or {}),
            "llm_model": settings.LLM_MODEL,
        }
        return result
