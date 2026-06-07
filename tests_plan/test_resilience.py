"""
Resilience 模块测试 — CircuitBreaker + retry + AgentLoop 错误恢复
"""

import asyncio
import pytest
import time

from harness.resilience import (
    CircuitBreaker, CircuitState,
    RetryConfig, retry_with_backoff,
    get_circuit_breaker, _BREAKER_REGISTRY,
)
from agent.loop import AgentLoop
from agent.llm import LLMErrorType, LLMResponse
from agent.types import Message, Role, ToolCall
from agent.context import ContextManager


# ── CircuitBreaker 单元测试 ──

class TestCircuitBreaker:
    def test_closed_by_default(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_open_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_rejects_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # 未达阈值
        assert cb.allow_request() is True

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.allow_request() is True  # 冷却后进入 half_open
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(
            failure_threshold=2, cooldown_seconds=0.05,
            half_open_max_calls=1, half_open_success_threshold=1,
        )
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()  # 进入 half_open
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        # 强制进入 half_open 模拟
        cb.state = CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_limits_concurrent(self):
        cb = CircuitBreaker(
            failure_threshold=1, cooldown_seconds=0.05,
            half_open_max_calls=1,
        )
        cb.record_failure()
        time.sleep(0.06)
        assert cb.allow_request() is True  # first probe
        assert cb.allow_request() is False  # second blocked (in_flight=1)

    def test_allow_request_respects_in_flight_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05, half_open_max_calls=1)
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()  # enters half_open, increments in_flight
        cb.record_success()  # decrements in_flight
        assert cb.allow_request() is True  # should be allowed again


# ── 全局注册表 ──

class TestCircuitBreakerRegistry:
    def setup_method(self):
        _BREAKER_REGISTRY.clear()

    def test_get_or_create(self):
        cb1 = get_circuit_breaker("test-breaker")
        cb2 = get_circuit_breaker("test-breaker")
        assert cb1 is cb2

    def test_shared_state_across_agents(self):
        cb1 = get_circuit_breaker("shared", failure_threshold=2)
        cb1.record_failure()
        cb1.record_failure()
        cb2 = get_circuit_breaker("shared")
        assert cb2.state == CircuitState.OPEN


# ── retry_with_backoff ──

class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_immediate_success(self):
        calls = []

        async def ok_fn():
            calls.append(1)
            return "done"

        result = await retry_with_backoff(ok_fn)
        assert result == "done"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary")
            return "ok"

        result = await retry_with_backoff(
            fail_twice,
            config=RetryConfig(max_retries=3, base_delay=0.01),
        )
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhaust_retries_raises(self):
        async def always_fail():
            raise ValueError("always")

        with pytest.raises(ValueError):
            await retry_with_backoff(
                always_fail,
                config=RetryConfig(max_retries=2, base_delay=0.01),
            )

    @pytest.mark.asyncio
    async def test_retry_based_on_result(self):
        """使用 should_retry_result 回调来决定是否重试"""
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse.error("busy", error_type=LLMErrorType.RATE_LIMIT, retryable=True)
            return LLMResponse(content="ok", tool_calls=[], finish_reason="stop", usage={})

        config = RetryConfig(
            max_retries=2,
            base_delay=0.01,
            should_retry_result=lambda r: r.finish_reason == "error" and r.retryable,
        )
        result = await retry_with_backoff(flaky, config=config)
        assert result.finish_reason == "stop"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_result_exhausted(self):
        async def always_error():
            return LLMResponse.error("busy", error_type=LLMErrorType.RATE_LIMIT, retryable=True)

        config = RetryConfig(
            max_retries=1,
            base_delay=0.01,
            should_retry_result=lambda r: r.finish_reason == "error" and r.retryable,
        )
        result = await retry_with_backoff(always_error, config=config)
        assert result.finish_reason == "error"


class TestBackoffDelayCalculation:
    def test_exponential_backoff(self):
        cfg = RetryConfig(base_delay=1.0, backoff_multiplier=2.0, max_delay=30.0)
        from harness.resilience import _compute_backoff_delay
        assert _compute_backoff_delay(cfg, 0) == 1.0
        assert _compute_backoff_delay(cfg, 1) == 2.0
        assert _compute_backoff_delay(cfg, 2) == 4.0

    def test_max_delay_cap(self):
        cfg = RetryConfig(base_delay=10.0, backoff_multiplier=10.0, max_delay=30.0)
        from harness.resilience import _compute_backoff_delay
        assert _compute_backoff_delay(cfg, 2) == 30.0


# ── AgentLoop 集成测试：错误恢复 ──

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


@pytest.mark.asyncio
async def test_loop_fatal_error_stops_immediately():
    fake_llm = FakeLLM([
        LLMResponse.error("auth failed", error_type=LLMErrorType.AUTH, retryable=False),
    ])
    agent = AgentLoop(
        llm=fake_llm,
        context=ContextManager(system_prompt="test"),
        max_consecutive_errors=5,
    )
    result = await agent.run("hello")
    assert "auth failed" in result or "LLM call failed" in result


@pytest.mark.asyncio
async def test_loop_consecutive_errors_threshold():
    # Provide enough errors to account for retry_with_backoff (max_retries=2 means 3 attempts)
    errors = [LLMResponse.error("timeout", error_type=LLMErrorType.TIMEOUT, retryable=True)
              for _ in range(30)]  # enough to exhaust consecutive threshold across turns
    fake_llm = FakeLLM(errors)
    agent = AgentLoop(
        llm=fake_llm,
        context=ContextManager(system_prompt="test"),
        max_consecutive_errors=3,
        circuit_name="consecutive-test",
    )
    agent._retry_config.max_retries = 0  # disable retry for this test
    result = await agent.run("hello")
    assert "consecutive" in result or "failed" in result or "LLM call failed" in result


@pytest.mark.asyncio
async def test_loop_recovers_after_tool_failure():
    """工具失败后 agent 继续下一轮（非致命）"""
    # Tool failure is handled at loop level - we need to check that the loop
    # continues after a tool returns success=False
    from agent.types import ToolCall

    # Simulate: LLM returns a tool call, then on next turn gives final answer
    fake_llm = FakeLLM([
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="tc1", name="echo", arguments={"text": "hi"})],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        ),
        LLMResponse(content="final answer", tool_calls=[], finish_reason="stop", usage={}),
    ])
    agent = AgentLoop(
        llm=fake_llm,
        context=ContextManager(system_prompt="test"),
    )
    result = await agent.run("hello")
    assert result is not None


@pytest.mark.asyncio
async def test_loop_max_turns():
    # LLM returns tool calls → loop continues; tool not found → tool error → loop continues
    fake_llm = FakeLLM(
        [LLMResponse(
            content="",
            tool_calls=[ToolCall(id=f"tc{i}", name="nonexistent", arguments={})],
            finish_reason="tool_calls",
            usage={},
        ) for i in range(20)]
    )
    agent = AgentLoop(
        llm=fake_llm,
        context=ContextManager(system_prompt="test"),
        max_turns=3,  # low limit
    )
    result = await agent.run("hello")
    assert "max reasoning turns" in result
