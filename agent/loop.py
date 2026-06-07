"""
Core agent loop: user message -> LLM -> tools -> LLM -> final answer.
"""

import asyncio
import json
import logging
import time
from typing import Callable, Optional

from .context import ContextManager
from .llm import LLMClient, LLMErrorType, LLMResponse
from .types import AgentState, AgentStatus, Message, Role, ToolCall, ToolResult
from harness.resilience import RetryConfig, get_circuit_breaker, retry_with_backoff

logger = logging.getLogger("agent.loop")


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        context: ContextManager,
        max_turns: int = 15,
        max_consecutive_errors: int = 3,
        circuit_name: str | None = None,
    ):
        self.llm = llm
        self.context = context
        self.max_turns = max_turns
        self.max_consecutive_errors = max_consecutive_errors

        self._tool_executor = None
        self._tool_selector = None
        self._tool_registry = None

        self._on_turn_start: Optional[Callable] = None
        self._on_turn_end: Optional[Callable] = None
        self._on_tool_call: Optional[Callable] = None
        self._on_tool_result: Optional[Callable] = None
        self._on_llm_response: Optional[Callable] = None
        self._on_status_change: Optional[Callable] = None

        circuit_key = circuit_name or f"{self.llm.base_url}:{self.llm.model}"
        self._circuit_breaker = get_circuit_breaker(
            circuit_key,
            failure_threshold=3,
            cooldown_seconds=30.0,
            half_open_max_calls=1,
            half_open_success_threshold=1,
        )
        self._retry_config = RetryConfig(
            max_retries=2,
            base_delay=1.0,
            backoff_multiplier=2.0,
            max_delay=10.0,
            should_retry_result=self._should_retry_llm_response,
            get_delay_for_result=self._delay_for_llm_response,
        )

        self._cancel_event: asyncio.Event = asyncio.Event()
        self._last_state: Optional[AgentState] = None

    def cancel(self):
        self._cancel_event.set()
        logger.info("Received cancel request")

    def reset_cancel(self):
        self._cancel_event.clear()

    async def _check_cancelled(self):
        if self._cancel_event.is_set():
            raise asyncio.CancelledError("User cancelled agent execution")

    @staticmethod
    def _capture_user_location(messages: list, current_message: str) -> str:
        """扫描对话历史，提取用户陈述的位置信息。"""
        # 如果当前消息包含位置声明，直接返回
        for prefix in ("我在", "我位于", "我住在", "我在广州"):
            if prefix in current_message:
                return current_message[:200]

        # 从历史消息中找最后一条含 "我在" 的用户消息
        for msg in reversed(messages):
            if msg.role == Role.USER and msg.content and "我在" in msg.content:
                return msg.content[:200]

        return ""

    def register_tool_executor(self, executor):
        self._tool_executor = executor

    def register_tool_selector(self, selector):
        self._tool_selector = selector

    def register_tool_registry(self, registry):
        self._tool_registry = registry

    def on_turn_start(self, callback: Callable[[AgentState], None]):
        self._on_turn_start = callback

    def on_turn_end(self, callback: Callable[[AgentState], None]):
        self._on_turn_end = callback

    def on_tool_call(self, callback: Callable[[ToolCall], None]):
        self._on_tool_call = callback

    def on_tool_result(self, callback: Callable[[ToolResult], None]):
        self._on_tool_result = callback

    def on_llm_response(self, callback: Callable[[dict], None]):
        self._on_llm_response = callback

    def on_status_change(self, callback: Callable[[AgentState], None]):
        self._on_status_change = callback

    def register_observer(self, observer):
        self.on_turn_start(observer.on_turn_start)
        self.on_turn_end(observer.on_turn_end)
        self.on_tool_call(observer.on_tool_call)
        self.on_tool_result(observer.on_tool_result)
        self.on_llm_response(observer.on_llm_response)
        if hasattr(observer, "on_status_change"):
            self.on_status_change(observer.on_status_change)

    def _set_status(self, state: AgentState, status: AgentStatus):
        state.status = status
        if self._on_status_change:
            self._on_status_change(state)

    async def _call_llm_with_resilience(self, messages, tools) -> LLMResponse:
        if not self._circuit_breaker.allow_request():
            logger.warning("Circuit breaker is open; skipping upstream call")
            return LLMResponse.error(
                "(circuit open) LLM API is temporarily unavailable, please retry later.",
                error_type=LLMErrorType.CIRCUIT_OPEN,
            )

        try:
            response = await retry_with_backoff(
                self.llm.chat,
                messages,
                tools=tools,
                config=self._retry_config,
            )
        except Exception as e:
            self._circuit_breaker.record_failure()
            return LLMResponse.error(
                f"(network error) {type(e).__name__}: {e}",
                error_type=LLMErrorType.UNKNOWN,
                retryable=True,
            )

        if response.finish_reason != "error":
            self._circuit_breaker.record_success()
        elif self._should_count_for_circuit(response):
            self._circuit_breaker.record_failure()

        return response

    @staticmethod
    def _should_retry_llm_response(response: LLMResponse) -> bool:
        return response.finish_reason == "error" and bool(response.retryable)

    def _delay_for_llm_response(self, response: LLMResponse, attempt: int) -> float | None:
        if response.retry_after_seconds is not None:
            return response.retry_after_seconds
        if response.error_type == LLMErrorType.RATE_LIMIT:
            return min(2.0 * (attempt + 1), self._retry_config.max_delay)
        return None

    @staticmethod
    def _should_count_for_circuit(response: LLMResponse) -> bool:
        return response.error_type in {
            LLMErrorType.RATE_LIMIT,
            LLMErrorType.TIMEOUT,
            LLMErrorType.CONNECTION,
            LLMErrorType.SERVER,
            LLMErrorType.UNKNOWN,
        }

    @staticmethod
    def _is_fatal_llm_error(response: LLMResponse) -> bool:
        return response.error_type in {
            LLMErrorType.AUTH,
            LLMErrorType.BAD_REQUEST,
            LLMErrorType.CONTEXT_LENGTH,
            LLMErrorType.INVALID_RESPONSE,
        }

    @staticmethod
    def _cache_key(messages: list[Message], tools: list[dict] | None) -> str:
        import hashlib

        relevant = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                relevant.append(f"s:{msg.content[:200]}")
        for msg in messages[-2:]:
            relevant.append(f"{msg.role}:{msg.content[:500]}")
        if tools:
            relevant.append(f"tools:{len(tools)}")
        return hashlib.md5("||".join(relevant).encode("utf-8", errors="replace")).hexdigest()

    async def run(self, user_message: str, previous_messages: list[Message] = None) -> str:
        state = AgentState()
        self._set_status(state, AgentStatus.THINKING)

        if previous_messages:
            state.messages.extend(previous_messages)
        state.messages.append(Message(role=Role.USER, content=user_message))

        # 扫描用户消息中的位置声明，持久化到 system prompt 避免被裁剪
        stated_location = self._capture_user_location(state.messages, user_message)
        if stated_location and not self.context.location_context:
            self.context.location_context = f"[用户陈述的位置] {stated_location}"

        logger.info("Agent loop started | user=%s", user_message[:80])

        consecutive_errors = 0
        self.reset_cancel()
        response_cache: dict[str, tuple[float, str, list[ToolCall], str]] = {}

        try:
            for turn in range(self.max_turns):
                await self._check_cancelled()
                state.turn_count = turn + 1

                if self._on_turn_start:
                    self._on_turn_start(state)

                messages = self.context.build_messages(state.messages, user_message=user_message)

                tools = None
                if self._tool_selector and self._tool_registry:
                    tools = self._tool_selector.build_tools_for_llm(user_message)
                elif self._tool_registry:
                    tools = self._tool_registry.get_tools_for_llm()

                await self._check_cancelled()
                cache_ttl = 30.0
                cache_key = self._cache_key(messages, tools)
                cached = response_cache.get(cache_key)

                if cached and time.monotonic() - cached[0] < cache_ttl:
                    response = LLMResponse(
                        content=cached[1],
                        tool_calls=cached[2],
                        finish_reason=cached[3],
                        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    )
                    logger.debug("Turn %s: response cache hit", turn + 1)
                else:
                    logger.debug(
                        "Turn %s: sending %s messages with %s tools",
                        turn + 1,
                        len(messages),
                        len(tools or []),
                    )
                    response = await self._call_llm_with_resilience(messages, tools)
                    if response.finish_reason != "error":
                        response_cache[cache_key] = (
                            time.monotonic(),
                            response.content or "",
                            response.tool_calls,
                            response.finish_reason,
                        )

                for key in state.token_usage:
                    state.token_usage[key] += response.usage.get(key, 0)

                if self._on_llm_response:
                    self._on_llm_response(response.usage)

                if response.finish_reason == "error":
                    consecutive_errors += 1

                    if self._is_fatal_llm_error(response):
                        self._set_status(state, AgentStatus.ERROR)
                        self._last_state = state
                        return response.content or "LLM call failed"

                    if consecutive_errors >= self.max_consecutive_errors:
                        self._set_status(state, AgentStatus.ERROR)
                        self._last_state = state
                        return (
                            f"Agent stopped after {consecutive_errors} consecutive LLM failures.\n"
                            f"Last error: {response.content}"
                        )

                    state.messages.append(
                        Message(role=Role.ASSISTANT, content=f"(call failed) {response.content}")
                    )
                    continue

                consecutive_errors = 0

                if response.tool_calls:
                    raw_tool_calls = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]

                    state.messages.append(
                        Message(
                            role=Role.ASSISTANT,
                            content=response.content or "",
                            tool_calls=raw_tool_calls,
                        )
                    )

                    self._set_status(state, AgentStatus.EXECUTING)

                    for tc in response.tool_calls:
                        await self._check_cancelled()
                        state.tool_call_history.append(tc)
                        if self._on_tool_call:
                            self._on_tool_call(tc)

                    async def _exec_one(tc: ToolCall) -> ToolResult:
                        tool = self._tool_registry.get(tc.name) if self._tool_registry else None
                        if tool is None:
                            return ToolResult(
                                tool_call_id=tc.id,
                                name=tc.name,
                                success=False,
                                output="",
                                error=f"Tool not found: '{tc.name}'",
                            )
                        return await self._tool_executor.execute(tc, tool)

                    results = await asyncio.gather(*[_exec_one(tc) for tc in response.tool_calls])

                    for tc, result in zip(response.tool_calls, results):
                        state.tool_result_history.append(result)
                        if self._on_tool_result:
                            self._on_tool_result(result)

                        result_text = result.output or f"(error) {result.error}"
                        state.messages.append(
                            Message(
                                role=Role.TOOL,
                                content=result_text,
                                tool_call_id=result.tool_call_id,
                                name=result.name,
                            )
                        )

                        if not result.success:
                            consecutive_errors += 1
                            logger.warning("Tool '%s' failed: %s", result.name, result.error)
                        else:
                            consecutive_errors = 0

                    # 首次成功调用后禁用 ip_geolocation，防止 LLM 反复获取位置
                    if any(r.name == "ip_geolocation" and r.success for r in results):
                        if self._tool_registry:
                            self._tool_registry.disable("ip_geolocation")
                            logger.info("Disabled ip_geolocation after first successful use")
                        # 把位置信息持久化到 system prompt 区域，避免被裁剪/过滤丢失
                        for r in results:
                            if r.name == "ip_geolocation" and r.success:
                                stated = self.context.location_context  # 可能已有用户声明的位置
                                ip_info = r.output.strip()
                                if stated and "[用户陈述的位置]" in stated:
                                    self.context.location_context = f"{stated}\n[IP定位] {ip_info}"
                                else:
                                    self.context.location_context = f"[已知位置信息] {ip_info}"

                    self._set_status(state, AgentStatus.THINKING)
                    if self._on_turn_end:
                        self._on_turn_end(state)
                    continue

                if response.content:
                    state.messages.append(Message(role=Role.ASSISTANT, content=response.content))

                self._set_status(state, AgentStatus.DONE)
                if self._on_turn_end:
                    self._on_turn_end(state)

                self._last_state = state
                logger.info(
                    "Agent loop finished | turns=%s tokens=%s tool_calls=%s",
                    state.turn_count,
                    state.token_usage["total_tokens"],
                    len(state.tool_call_history),
                )

                if response.content:
                    return response.content
                for msg in reversed(state.messages):
                    if msg.role == Role.ASSISTANT and msg.content and msg.content not in ("", "(call failed) "):
                        return msg.content
                for result in reversed(state.tool_result_history):
                    if result.success and result.output:
                        return f"(execution result) {result.output[:2000]}"
                return "(Agent finished without text output)"

            self._set_status(state, AgentStatus.MAX_TURNS)
            if self._on_turn_end:
                self._on_turn_end(state)
            self._last_state = state
            logger.warning("Reached max turns: %s", self.max_turns)
            return (
                f"Reached max reasoning turns ({self.max_turns}); agent stopped.\n"
                f"Tool calls: {len(state.tool_call_history)}\n"
                f"Tokens used: {state.token_usage['total_tokens']}"
            )
        except asyncio.CancelledError:
            self._set_status(state, AgentStatus.CANCELLED)
            if self._on_turn_end:
                self._on_turn_end(state)
            self._last_state = state
            logger.info("Agent cancelled after %s turns", state.turn_count)
            return (
                "Agent was cancelled by the user.\n"
                f"Turns completed: {state.turn_count}\n"
                f"Tool calls: {len(state.tool_call_history)}"
            )
