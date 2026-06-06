"""
LLM client wrapper, defaulting to a DeepSeek-compatible chat API.
"""

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

from .types import Message, ToolCall


class LLMErrorType(str, Enum):
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    AUTH = "auth"
    BAD_REQUEST = "bad_request"
    CONTEXT_LENGTH = "context_length"
    SERVER = "server_error"
    INVALID_RESPONSE = "invalid_response"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


@dataclass
class LLMResponse:
    """Normalized LLM response."""

    content: Optional[str]
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: dict[str, int]
    error_type: Optional[str] = None
    status_code: Optional[int] = None
    retryable: bool = False
    retry_after_seconds: Optional[float] = None

    @classmethod
    def error(
        cls,
        content: str,
        *,
        error_type: str,
        status_code: Optional[int] = None,
        retryable: bool = False,
        retry_after_seconds: Optional[float] = None,
    ) -> "LLMResponse":
        return cls(
            content=content,
            tool_calls=[],
            finish_reason="error",
            usage={},
            error_type=error_type,
            status_code=status_code,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        )


class LLMClient:
    """
    Lightweight OpenAI-compatible LLM client.
    """

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None,
    ):
        self.api_key = (
            api_key
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY", "")
        )
        self.base_url = (
            (base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"))
        ).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "deepseek-v4-flash")

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"

        body = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        proxies = {}
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if http_proxy:
            proxies["http://"] = http_proxy
        if https_proxy:
            proxies["https://"] = https_proxy

        async with httpx.AsyncClient(
            timeout=120.0,
            proxy=proxies.get("https://") or proxies.get("http://"),
        ) as client:
            try:
                resp = await client.post(url, json=body, headers=headers)
            except httpx.ConnectError as e:
                return LLMResponse.error(
                    f"(connect error) Unable to reach {self.base_url}: {e}",
                    error_type=LLMErrorType.CONNECTION,
                    retryable=True,
                )
            except httpx.TimeoutException:
                return LLMResponse.error(
                    f"(timeout) Request to {self.base_url} timed out",
                    error_type=LLMErrorType.TIMEOUT,
                    retryable=True,
                )
            except Exception as e:
                return LLMResponse.error(
                    f"(network error) {type(e).__name__}: {e}",
                    error_type=LLMErrorType.UNKNOWN,
                    retryable=True,
                )

        if resp.status_code != 200:
            return self._build_http_error_response(resp)

        try:
            data = resp.json()
        except ValueError as e:
            return LLMResponse.error(
                f"(invalid response) JSON parse failed: {e}",
                error_type=LLMErrorType.INVALID_RESPONSE,
            )

        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as e:
            return LLMResponse.error(
                f"(invalid response) Missing choices/message: {e}",
                error_type=LLMErrorType.INVALID_RESPONSE,
            )

        finish = choice.get("finish_reason", "stop")
        usage = data.get("usage", {})

        tool_calls = []
        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            try:
                tool_calls.append(ToolCall.from_dict(tc))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return LLMResponse(
            content=message.get("content", ""),
            tool_calls=tool_calls,
            finish_reason=finish,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )

    def _build_http_error_response(self, resp: httpx.Response) -> LLMResponse:
        error_detail = resp.text[:500]
        retry_after_seconds = self._parse_retry_after(resp.headers.get("retry-after"))
        status_code = resp.status_code

        if status_code == 400:
            error_type = self._classify_bad_request(error_detail)
            return LLMResponse.error(
                f"(API error {status_code}) {error_detail}",
                error_type=error_type,
                status_code=status_code,
                retryable=False,
            )
        if status_code in (401, 403):
            return LLMResponse.error(
                f"(API error {status_code}) {error_detail}",
                error_type=LLMErrorType.AUTH,
                status_code=status_code,
                retryable=False,
            )
        if status_code == 429:
            return LLMResponse.error(
                f"(API error {status_code}) {error_detail}",
                error_type=LLMErrorType.RATE_LIMIT,
                status_code=status_code,
                retryable=True,
                retry_after_seconds=retry_after_seconds,
            )
        if status_code in (408, 499, 502, 503, 504) or status_code >= 500:
            return LLMResponse.error(
                f"(API error {status_code}) {error_detail}",
                error_type=LLMErrorType.SERVER,
                status_code=status_code,
                retryable=True,
                retry_after_seconds=retry_after_seconds,
            )
        return LLMResponse.error(
            f"(API error {status_code}) {error_detail}",
            error_type=LLMErrorType.BAD_REQUEST,
            status_code=status_code,
            retryable=False,
        )

    @staticmethod
    def _classify_bad_request(error_detail: str) -> str:
        text = (error_detail or "").lower()
        context_markers = [
            "context length",
            "maximum context length",
            "too many tokens",
            "prompt is too long",
            "maximum tokens",
        ]
        if any(marker in text for marker in context_markers):
            return LLMErrorType.CONTEXT_LENGTH
        return LLMErrorType.BAD_REQUEST

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        return max(0.0, seconds)
