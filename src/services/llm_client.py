"""선택적 LLM Q&A 클라이언트.

Ollama 네이티브 API와 OpenAI 호환 API를 지원한다. 어떤 네트워크 오류도
호출자에게 전파하지 않고 ``None``을 반환해 기존 evidence 답변을 유지한다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmStatus:
    enabled: bool
    available: bool
    model: str
    endpoint: str
    last_error: str | None = None


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        return f"connection failed: {exc.reason}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return type(exc).__name__


def _extract_answer(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None

    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = choices[0]
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

    response = data.get("response")
    if isinstance(response, str) and response.strip():
        return response.strip()
    return None


SYSTEM_PROMPT = (
    "너는 동아리 소개 기반 Q&A 답변자다. "
    "반드시 사용자 메시지의 [근거]에 적힌 문장만 사용해서 답변해. "
    "근거에 없는 내용이나 일반 지식은 추측하지 마. "
    "모든 답변은 한국어로 간결하게 작성해."
)


class LlmClient:
    def __init__(self) -> None:
        self._lock = Lock()
        self._probe_cached: bool | None = None
        self._probe_checked_at = 0.0
        self._unavailable_until = 0.0
        self._last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(settings.LLM_ENABLED)

    def _base_url(self) -> str:
        return (settings.LLM_BASE_URL or "").rstrip("/")

    def _is_openai_mode(self) -> bool:
        base = self._base_url()
        return base.endswith(("/v1", "/chat/completions"))

    def chat_url(self) -> str:
        base = self._base_url()
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/api/chat"

    def probe_url(self) -> str:
        base = self._base_url().removesuffix("/chat/completions")
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/api/tags"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._is_openai_mode() and settings.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
        return headers

    def probe(self, *, force: bool = False) -> bool:
        if not self.configured:
            return False

        now = time.monotonic()
        with self._lock:
            if (
                not force
                and self._probe_cached is not None
                and now - self._probe_checked_at < settings.LLM_HEALTH_TTL_SECONDS
            ):
                return self._probe_cached

        reachable = False
        try:
            request = Request(self.probe_url(), headers=self._headers(), method="GET")
            timeout = max(
                0.5,
                min(settings.LLM_PROBE_TIMEOUT_SECONDS, settings.LLM_TIMEOUT_SECONDS),
            )
            with urlopen(request, timeout=timeout) as response:
                response.read(4_096)
            reachable = True
        except Exception as exc:  # noqa: BLE001 - LLM 장애는 evidence 폴백 대상
            self._last_error = _describe_error(exc)
            logger.warning("LLM health probe failed: %s", self._last_error)
        else:
            self._last_error = None
        finally:
            with self._lock:
                self._probe_cached = reachable
                self._probe_checked_at = time.monotonic()
        return reachable

    def available(self) -> bool:
        if not self.configured:
            return False
        with self._lock:
            if time.monotonic() < self._unavailable_until:
                return False
        return self.probe()

    def status(self) -> LlmStatus:
        return LlmStatus(
            enabled=self.configured,
            available=self.available() if self.configured else False,
            model=settings.LLM_MODEL,
            endpoint=self.chat_url(),
            last_error=self._last_error,
        )

    def _mark_unavailable(self) -> None:
        with self._lock:
            self._unavailable_until = time.monotonic() + max(
                0, settings.LLM_RETRY_COOLDOWN_SECONDS
            )
            self._probe_cached = False
            self._probe_checked_at = time.monotonic()

    def generate_answer(
        self,
        question: str,
        club_name: str,
        evidence: list[str],
    ) -> str | None:
        if not self.configured or not self.available():
            return None

        evidence_lines = [item.strip() for item in evidence if item and item.strip()]
        if not evidence_lines:
            return None

        user_content = (
            f"동아리명: {club_name or '알 수 없음'}\n"
            "[근거]\n"
            + "\n".join(f"- {line}" for line in evidence_lines)
            + f"\n\n질문: {question}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        if self._is_openai_mode():
            payload: dict[str, Any] = {
                "model": settings.LLM_MODEL,
                "messages": messages,
                "stream": False,
                "temperature": settings.LLM_TEMPERATURE,
                "max_tokens": settings.LLM_MAX_TOKENS,
            }
        else:
            payload = {
                "model": settings.LLM_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": settings.LLM_TEMPERATURE,
                    "num_predict": settings.LLM_MAX_TOKENS,
                },
            }

        try:
            request = Request(
                self.chat_url(),
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urlopen(request, timeout=settings.LLM_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            self._last_error = _describe_error(exc)
            logger.warning("LLM answer generation failed: %s", self._last_error)
            self._mark_unavailable()
            return None

        answer = _extract_answer(data)
        if not answer:
            self._last_error = "empty response"
            self._mark_unavailable()
            return None
        if answer.startswith("답변:"):
            answer = answer[len("답변:") :].strip()
        self._last_error = None
        return answer or None


_client = LlmClient()


def get_llm_client() -> LlmClient:
    return _client
