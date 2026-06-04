"""
Observability 模块 —— Agent 运行的可观测性

三个维度：
1. 日志追踪：每个 turn 的输入/输出/工具调用
2. Token 统计：每次请求的 token 消耗累计
3. 性能指标：每轮耗时、工具执行耗时

这些数据用于：
- 调试：为什么 Agent 做错了某步？
- 优化：哪类工具最慢？哪轮消耗 token 最多？
- 成本：这次对话花了多少钱？
"""

import time
import logging
import json
from dataclasses import dataclass, field
from typing import Optional
from agent.types import ToolCall, ToolResult, AgentState

logger = logging.getLogger("harness.observability")


@dataclass
class TurnRecord:
    """单轮记录"""
    turn_number: int
    timestamp: float
    llm_duration_ms: float = 0
    tool_calls: list[str] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    token_prompt: int = 0
    token_completion: int = 0


@dataclass
class SessionMetrics:
    """会话级指标"""
    session_start: float = field(default_factory=time.monotonic)
    total_turns: int = 0
    total_tool_calls: int = 0
    total_tool_errors: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    turns: list[TurnRecord] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def duration_seconds(self) -> float:
        return time.monotonic() - self.session_start

    @property
    def tool_error_rate(self) -> float:
        if self.total_tool_calls == 0:
            return 0.0
        return self.total_tool_errors / self.total_tool_calls

    def summary(self) -> str:
        """生成可读摘要"""
        return (
            f"会话统计:\n"
            f"  总轮次:     {self.total_turns}\n"
            f"  总耗时:     {self.duration_seconds:.1f}s\n"
            f"  工具调用:   {self.total_tool_calls} 次 "
            f"(失败 {self.total_tool_errors} 次, "
            f"错误率 {self.tool_error_rate:.1%})\n"
            f"  Token 消耗: {self.total_tokens} "
            f"(输入 {self.total_prompt_tokens}, 输出 {self.total_completion_tokens})\n"
            f"  估算成本:   ${self._estimate_cost():.4f}"
        )

    def _estimate_cost(self) -> float:
        # DeepSeek 价格（极便宜）：输入 ¥1/百万 token，输出 ¥2/百万 token
        # 换算约 $0.14/M 输入, $0.28/M 输出
        prompt_cost = self.total_prompt_tokens / 1_000_000 * 0.14
        completion_cost = self.total_completion_tokens / 1_000_000 * 0.28
        return prompt_cost + completion_cost

    def to_json(self) -> str:
        return json.dumps({
            "total_turns": self.total_turns,
            "total_tool_calls": self.total_tool_calls,
            "total_tool_errors": self.total_tool_errors,
            "total_tokens": self.total_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "duration_seconds": self.duration_seconds,
            "estimated_cost_usd": self._estimate_cost(),
        }, ensure_ascii=False, indent=2)


class AgentObserver:
    """
    Agent 观测器 —— 挂载到 AgentLoop 的各个钩子上

    用法:
        observer = AgentObserver()
        agent.on_turn_start(observer.on_turn_start)
        agent.on_tool_call(observer.on_tool_call)
        agent.on_tool_result(observer.on_tool_result)
    """

    def __init__(self):
        self.metrics = SessionMetrics()
        self._current_turn: Optional[TurnRecord] = None

    def on_turn_start(self, state: AgentState):
        self._current_turn = TurnRecord(
            turn_number=state.turn_count,
            timestamp=time.monotonic(),
        )

    def on_tool_call(self, tool_call: ToolCall):
        self.metrics.total_tool_calls += 1
        if self._current_turn:
            self._current_turn.tool_calls.append(tool_call.name)
        logger.info(
            f"[Turn {self.metrics.total_turns+1}] 调用工具: "
            f"{tool_call.name}({json.dumps(tool_call.arguments, ensure_ascii=False)})"
        )

    def on_tool_result(self, result: ToolResult):
        if not result.success:
            self.metrics.total_tool_errors += 1
        if self._current_turn:
            status = "OK" if result.success else "FAIL"
            self._current_turn.tool_results.append(
                f"{result.name}: {status} ({result.duration_ms:.0f}ms)"
            )
        logger.info(
            f"[Turn {self.metrics.total_turns+1}] 工具结果: "
            f"{result.name} -> {'成功' if result.success else '失败'}"
            f"{' - ' + result.error if result.error else ''}"
            f" ({result.duration_ms:.0f}ms)"
        )

    def on_turn_end(self):
        if self._current_turn:
            self.metrics.turns.append(self._current_turn)
            self.metrics.total_turns += 1
        self._current_turn = None

    def on_llm_response(self, usage: dict):
        self.metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
        self.metrics.total_completion_tokens += usage.get("completion_tokens", 0)
