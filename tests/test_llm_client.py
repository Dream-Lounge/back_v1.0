import json
import time

from src.core.config import settings
from src.services.llm_client import LlmClient, _extract_answer


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_extract_answer_supports_ollama_and_openai_shapes():
    assert _extract_answer({"message": {"content": " Ollama 답변 "}}) == "Ollama 답변"
    assert (
        _extract_answer({"choices": [{"message": {"content": " OpenAI 답변 "}}]})
        == "OpenAI 답변"
    )


def test_disabled_client_does_not_probe_network(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    monkeypatch.setattr(
        "src.services.llm_client.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )

    client = LlmClient()

    assert client.available() is False
    assert client.generate_answer("질문", "동아리", ["근거"]) is None


def test_ollama_generation_uses_configured_model_and_evidence(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(settings, "LLM_MODEL", "test-model")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"message": {"content": "답변: 근거 기반 답변"}})

    monkeypatch.setattr("src.services.llm_client.urlopen", fake_urlopen)
    client = LlmClient()
    client._probe_cached = True
    client._probe_checked_at = time.monotonic()

    answer = client.generate_answer("무슨 활동을 해?", "테스트 동아리", ["영상 제작"])

    assert answer == "근거 기반 답변"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["body"]["model"] == "test-model"
    assert "영상 제작" in captured["body"]["messages"][1]["content"]
