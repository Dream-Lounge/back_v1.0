from types import SimpleNamespace

from src.services.qa_answer_service import QaAnswerService
from tests.test_recommendations import seed_recommendation_data


class FakeLlmClient:
    def __init__(
        self,
        *,
        configured: bool,
        available: bool = False,
        answer: str | None = None,
    ) -> None:
        self.configured = configured
        self._available = available
        self._answer = answer
        self.generate_calls = 0

    def available(self) -> bool:
        return self._available

    def generate_answer(
        self,
        question: str,
        club_name: str,
        evidence: list[str],
    ) -> str | None:
        self.generate_calls += 1
        assert question
        assert club_name == "영상제작 동아리"
        assert evidence
        return self._answer

    def status(self):
        return SimpleNamespace(
            enabled=self.configured,
            available=self._available,
            model="test-model",
        )


def test_qa_keeps_existing_answer_when_llm_is_disabled(db, seeded_club):
    club = seed_recommendation_data(db, seeded_club)
    llm = FakeLlmClient(configured=False)

    result = QaAnswerService(db, llm_client=llm).answer(
        "초보도 지원할 수 있어?",
        club.id,
    )

    assert result["supported"] is True
    assert "초보" in result["answer"]
    assert result["answer_source"] == "evidence"
    assert llm.generate_calls == 0


def test_qa_uses_llm_only_after_existing_evidence_is_found(db, seeded_club):
    club = seed_recommendation_data(db, seeded_club)
    llm = FakeLlmClient(
        configured=True,
        available=True,
        answer="초보자도 영상 편집 활동에 참여할 수 있습니다.",
    )

    result = QaAnswerService(db, llm_client=llm).answer(
        "초보도 지원할 수 있어?",
        club.id,
    )

    assert result["answer"] == "초보자도 영상 편집 활동에 참여할 수 있습니다."
    assert result["answer_source"] == "llm"
    assert result["model_info"]["llm_model"] == "gemma3:4b"
    assert llm.generate_calls == 1


def test_qa_does_not_call_llm_for_unsupported_question(db, seeded_club):
    club = seed_recommendation_data(db, seeded_club)
    llm = FakeLlmClient(
        configured=True,
        available=True,
        answer="근거 없이 생성되면 안 되는 답변",
    )

    result = QaAnswerService(db, llm_client=llm).answer(
        "기숙사를 제공해?",
        club.id,
    )

    assert result["supported"] is False
    assert result["answer_source"] == "evidence"
    assert llm.generate_calls == 0


def test_public_status_does_not_expose_internal_endpoint_or_error(db):
    llm = FakeLlmClient(configured=True, available=True)

    status = QaAnswerService(db, llm_client=llm).public_status()

    assert status == {
        "enabled": True,
        "available": True,
        "model": "test-model",
    }
