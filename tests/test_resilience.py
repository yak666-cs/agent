import httpx
import pytest

from agent.context import ContextManager
from agent.llm import LLMClient, LLMErrorType, LLMResponse
from agent.loop import AgentLoop
from agent.types import Message, Role


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.base_url = "https://example.test/v1"
        self.model = "fake-model"

    async def chat(self, messages, tools=None):
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="ok", tool_calls=[], finish_reason="stop", usage={})


def build_agent(fake_llm, circuit_name: str) -> AgentLoop:
    agent = AgentLoop(
        llm=fake_llm,
        context=ContextManager(system_prompt="test"),
        circuit_name=circuit_name,
    )
    agent._retry_config.base_delay = 0.0
    agent._retry_config.max_delay = 0.0
    return agent


def test_llm_client_classifies_rate_limit():
    client = LLMClient(api_key="x", base_url="https://example.test/v1", model="fake")
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(
        429,
        headers={"retry-after": "7"},
        json={"error": {"message": "rate limited"}},
        request=request,
    )

    result = client._build_http_error_response(response)

    assert result.finish_reason == "error"
    assert result.error_type == LLMErrorType.RATE_LIMIT
    assert result.retryable is True
    assert result.retry_after_seconds == 7.0


@pytest.mark.asyncio
async def test_agent_loop_retries_retryable_llm_errors():
    fake_llm = FakeLLM(
        [
            LLMResponse.error("busy", error_type=LLMErrorType.RATE_LIMIT, retryable=True),
            LLMResponse.error("busy", error_type=LLMErrorType.RATE_LIMIT, retryable=True),
            LLMResponse(content="done", tool_calls=[], finish_reason="stop", usage={}),
        ]
    )
    agent = build_agent(fake_llm, "retry-test")

    response = await agent._call_llm_with_resilience(
        [Message(role=Role.USER, content="hello")],
        tools=None,
    )

    assert fake_llm.calls == 3
    assert response.finish_reason == "stop"
    assert response.content == "done"


@pytest.mark.asyncio
async def test_circuit_breaker_is_shared_across_agents():
    failing_llm = FakeLLM(
        [
            LLMResponse.error("server down", error_type=LLMErrorType.SERVER, retryable=False),
            LLMResponse.error("server down", error_type=LLMErrorType.SERVER, retryable=False),
            LLMResponse.error("server down", error_type=LLMErrorType.SERVER, retryable=False),
        ]
    )
    agent_a = build_agent(failing_llm, "shared-breaker-test")

    for _ in range(3):
        await agent_a._call_llm_with_resilience([Message(role=Role.USER, content="hello")], tools=None)

    healthy_llm = FakeLLM([LLMResponse(content="ok", tool_calls=[], finish_reason="stop", usage={})])
    agent_b = build_agent(healthy_llm, "shared-breaker-test")

    blocked = await agent_b._call_llm_with_resilience(
        [Message(role=Role.USER, content="hello")],
        tools=None,
    )

    assert blocked.finish_reason == "error"
    assert blocked.error_type == LLMErrorType.CIRCUIT_OPEN
    assert healthy_llm.calls == 0
