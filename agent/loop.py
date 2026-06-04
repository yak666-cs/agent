"""
Agent Loop 核心循环

这是整个项目的核心 —— Message → LLM → Response → (Tool Call → Execute → Result → LLM) → Final Answer

循环逻辑本身很简洁（不到 50 行），但每个环节都包含着 design decision：

┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Message  │ ──→ │   LLM    │ ──→ │ Response │ ──→ │   Done?  │──→ 返回
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                       ↑                │
                       │         tool_calls?
                       │                │ yes
                       │                ↓
                       │         ┌──────────┐
                       └──────── │ Execute  │
                                 └──────────┘

关键设计决策（面试中要能讲清楚）：

1. 最大轮次（max_turns）：防止无限循环。
   - 太大会浪费 token，太小则复杂任务完不成
   - Claude Code 默认约 25 轮，这里设 15 轮

2. 工具调用循环：
   - LLM 可能一次返回多个 tool_call（并行），也可能逐个返回（串行）
   - 这里选择"全部执行完再回传结果"—— 简单且支持并行
   - 也可以选择"逐个执行并回传"—— 更安全但更慢

3. 终止条件：
   - LLM 返回 finish_reason="stop"（自然结束）
   - 达到 max_turns
   - 用户中断（Ctrl+C）
   - LLM 返回错误

4. 错误处理：
   - 工具执行失败 → 将错误信息作为 tool result 回传 LLM
   - LLM 通常能看懂错误并调整策略
   - 如果连续 3 个工具都失败 → 主动终止并报告
"""

import logging
import json
import asyncio
from typing import Optional, Callable, Awaitable

from .types import (
    Message, Role, AgentState, AgentStatus, ToolCall, ToolResult
)
from .llm import LLMClient, LLMResponse
from .context import ContextManager

logger = logging.getLogger("agent.loop")


class AgentLoop:
    """
    Agent 主循环。

    用法:
        agent = AgentLoop(llm_client, context_manager)
        agent.register_tool_executor(my_executor)

        result = await agent.run("帮我看看哪个进程最占 CPU")
    """

    def __init__(
        self,
        llm: LLMClient,
        context: ContextManager,
        max_turns: int = 15,
        max_consecutive_errors: int = 3,
    ):
        self.llm = llm
        self.context = context
        self.max_turns = max_turns
        self.max_consecutive_errors = max_consecutive_errors

        # 依赖注入
        self._tool_executor = None
        self._tool_selector = None
        self._tool_registry = None

        # 回调钩子
        self._on_turn_start: Optional[Callable] = None
        self._on_tool_call: Optional[Callable] = None
        self._on_tool_result: Optional[Callable] = None

        # 中断控制
        self._cancel_event: asyncio.Event = asyncio.Event()

    def cancel(self):
        """请求中断 Agent 循环"""
        self._cancel_event.set()
        logger.info("收到取消请求")

    def reset_cancel(self):
        """重置取消状态（复用 Agent 时）"""
        self._cancel_event.clear()

    async def _check_cancelled(self):
        """在循环关键点检查是否被取消"""
        if self._cancel_event.is_set():
            raise asyncio.CancelledError("用户中断了 Agent 执行")

    # ---- 依赖注入 ----

    def register_tool_executor(self, executor):
        self._tool_executor = executor

    def register_tool_selector(self, selector):
        self._tool_selector = selector

    def register_tool_registry(self, registry):
        self._tool_registry = registry

    def on_turn_start(self, callback: Callable[["AgentState"], None]):
        self._on_turn_start = callback

    def on_tool_call(self, callback: Callable[[ToolCall], None]):
        self._on_tool_call = callback

    def on_tool_result(self, callback: Callable[[ToolResult], None]):
        self._on_tool_result = callback

    # ---- 主循环 ----

    def _cache_key(self, messages: list[Message], tools: list[dict] | None) -> str:
        """为 LLM 请求生成缓存 key。"""
        import hashlib
        # 只取最后 2 条消息 + system prompt 做 key（兼顾命中率与安全性）
        relevant = []
        for m in messages:
            if m.role == Role.SYSTEM:
                relevant.append(f"s:{m.content[:200]}")
        for m in messages[-2:]:
            relevant.append(f"{m.role}:{m.content[:500]}")
        if tools:
            relevant.append(f"tools:{len(tools)}")
        raw = "||".join(relevant)
        return hashlib.md5(raw.encode()).hexdigest()

    async def run(self, user_message: str, previous_messages: list[Message] = None) -> str:
        """
        运行 Agent Loop。

        参数:
            user_message: 用户输入
            previous_messages: 可选。之前会话的消息历史，会在新用户消息之前注入

        返回:
            Agent 的最终回复文本
        """
        state = AgentState()
        state.status = AgentStatus.THINKING

        # 如果有历史消息，先注入（不包含 system prompt，build_messages 会加）
        if previous_messages:
            state.messages.extend(previous_messages)
        # 初始化消息历史
        state.messages.append(Message(role=Role.USER, content=user_message))

        logger.info(f"Agent Loop 启动 | 用户: {user_message[:80]}...")

        consecutive_errors = 0
        self.reset_cancel()

        # 响应缓存（LLM 返回后缓存，同一个 key 且 TTL 内直接复用）
        import time
        _response_cache: dict[str, tuple[float, str, list[ToolCall], str]] = {}

        try:
            for turn in range(self.max_turns):
                await self._check_cancelled()
                state.turn_count = turn + 1

                # 钩子：轮次开始
                if self._on_turn_start:
                    self._on_turn_start(state)

                # 1. 构建本次请求的消息列表（含上下文裁剪）
                messages = self.context.build_messages(state.messages)

                # 2. 选择工具集（Tool Selector 发挥作用的地方）
                tools = None
                if self._tool_selector and self._tool_registry:
                    tools = self._tool_selector.build_tools_for_llm(user_message)
                elif self._tool_registry:
                    tools = self._tool_registry.get_tools_for_llm()

                # 3. 调用 LLM（带响应缓存）
                await self._check_cancelled()
                cache_ttl = 2.0  # 2 秒内相同请求命中缓存
                ckey = self._cache_key(messages, tools)
                cached = _response_cache.get(ckey)
                if cached and time.monotonic() - cached[0] < cache_ttl:
                    response = LLMResponse(
                        content=cached[1],
                        tool_calls=cached[2],
                        finish_reason=cached[3],
                        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    )
                    logger.debug(f"Turn {turn+1}: 响应缓存命中")
                else:
                    logger.debug(f"Turn {turn+1}: 发送 {len(messages)} 条消息，"
                                f"{len(tools or [])} 个工具")
                    response = await self.llm.chat(messages, tools=tools)
                    if response.finish_reason != "error":
                        _response_cache[ckey] = (
                            time.monotonic(),
                            response.content or "",
                            response.tool_calls,
                            response.finish_reason,
                        )

                # 更新 token 统计
                for k in state.token_usage:
                    state.token_usage[k] += response.usage.get(k, 0)

                # 4. 处理 LLM 响应
                if response.finish_reason == "error":
                    consecutive_errors += 1
                    if consecutive_errors >= self.max_consecutive_errors:
                        state.status = AgentStatus.ERROR
                        self._last_state = state
                        return f"Agent 连续 {consecutive_errors} 次调用失败，已终止。\n最后错误: {response.content}"
                    # 回传错误信息让 LLM 自我纠正
                    state.messages.append(Message(
                        role=Role.ASSISTANT,
                        content=f"(调用失败) {response.content}"
                    ))
                    continue

                consecutive_errors = 0  # 成功，重置错误计数

                # 5. 判断：有工具调用？
                if response.tool_calls:
                    # 5a. 将 ToolCall 转为 OpenAI/DeepSeek 格式
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

                    # 记录 assistant 消息（必须包含 tool_calls，否则 API 报错）
                    state.messages.append(Message(
                        role=Role.ASSISTANT,
                        content=response.content or "",
                        tool_calls=raw_tool_calls,
                    ))

                    # 5b. 执行所有工具调用
                    state.status = AgentStatus.EXECUTING
                    for tc in response.tool_calls:
                        await self._check_cancelled()
                        state.tool_call_history.append(tc)

                        if self._on_tool_call:
                            self._on_tool_call(tc)

                        # 获取 Tool 实例并执行
                        tool = self._tool_registry.get(tc.name) if self._tool_registry else None
                        if tool is None:
                            result = ToolResult(
                                tool_call_id=tc.id,
                                name=tc.name,
                                success=False,
                                error=f"未找到 Tool: '{tc.name}'",
                            )
                        else:
                            result = await self._tool_executor.execute(tc, tool)

                        state.tool_result_history.append(result)

                        if self._on_tool_result:
                            self._on_tool_result(result)

                        # 将工具结果作为 tool 消息回传
                        result_text = result.output or f"(错误) {result.error}"
                        state.messages.append(Message(
                            role=Role.TOOL,
                            content=result_text,
                            tool_call_id=result.tool_call_id,
                            name=result.name,
                        ))

                        if not result.success:
                            consecutive_errors += 1
                            logger.warning(
                                f"工具 '{result.name}' 执行失败: {result.error}"
                            )
                        else:
                            consecutive_errors = 0

                    state.status = AgentStatus.THINKING
                    # 继续循环，把工具结果发给 LLM
                    continue

                # 5c. 没有工具调用 —— 这是最终回复
                if response.content:
                    state.messages.append(Message(
                        role=Role.ASSISTANT,
                        content=response.content,
                    ))

                state.status = AgentStatus.DONE
                self._last_state = state
                logger.info(
                    f"Agent Loop 完成 | {state.turn_count} 轮 | "
                    f"Token: {state.token_usage['total_tokens']} | "
                    f"工具调用: {len(state.tool_call_history)} 次"
                )
                return response.content or "(Agent 完成，无文本输出)"

            # 达到最大轮次
            state.status = AgentStatus.MAX_TURNS
            self._last_state = state
            logger.warning(f"达到最大轮次 {self.max_turns}，强制终止")
            return (
                f"已达到最大推理轮次（{self.max_turns}），Agent 已终止。\n"
                f"共调用 {len(state.tool_call_history)} 次工具，"
                f"消耗 {state.token_usage['total_tokens']} tokens。\n"
                f"请尝试将任务拆分为更小的步骤重新提问。"
            )
        except asyncio.CancelledError:
            state.status = AgentStatus.CANCELLED
            self._last_state = state
            logger.info(f"Agent 被用户中断，已执行 {state.turn_count} 轮")
            return (
                f"Agent 已被用户中断。\n"
                f"已执行 {state.turn_count} 轮，调用 {len(state.tool_call_history)} 次工具。\n"
                f"可以继续提出新的问题。"
            )
