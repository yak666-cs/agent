"""
Observability helpers for agent execution metrics, traces, and state snapshots.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any, Optional

from agent.types import AgentState, AgentStatus, ToolCall, ToolResult

logger = logging.getLogger("harness.observability")


MODEL_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (1.0, 2.0),
    "deepseek-v4-pro": (3.0, 6.0),
    "deepseek-chat": (2.0, 8.0),
    "deepseek-reasoner": (4.0, 16.0),
    "deepseek-v3": (2.0, 8.0),
    "deepseek-r1": (4.0, 16.0),
    "gpt-4o": (18.0, 72.0),
    "gpt-4o-mini": (1.08, 4.32),
    "claude-sonnet-4": (21.6, 108.0),
    "claude-haiku-3.5": (5.76, 28.8),
}
DEFAULT_PRICE = (3.0, 6.0)


def estimate_cost(prompt_tokens: int, completion_tokens: int, model: str = "") -> float:
    price = MODEL_PRICING.get(model, DEFAULT_PRICE)
    return (
        prompt_tokens / 1_000_000 * price[0]
        + completion_tokens / 1_000_000 * price[1]
    )


@dataclass
class TurnRecord:
    turn_number: int
    timestamp: float
    llm_duration_ms: float = 0.0
    tool_calls: list[str] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    token_prompt: int = 0
    token_completion: int = 0

    @property
    def duration_ms(self) -> float:
        return (time.monotonic() - self.timestamp) * 1000 if self.timestamp else 0.0


@dataclass
class StateSnapshot:
    timestamp: float
    turn: int
    status: str
    message_count: int
    tool_calls: int
    tool_results: int
    total_tokens: int
    last_user_preview: str = ""
    last_assistant_preview: str = ""


@dataclass
class TraceEvent:
    timestamp: float
    kind: str
    node: str
    turn: int
    status: str
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionMetrics:
    session_start: float = field(default_factory=time.monotonic)
    model: str = ""
    total_turns: int = 0
    total_tool_calls: int = 0
    total_tool_errors: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_llm_duration_ms: float = 0.0
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

    @property
    def estimated_cost_cny(self) -> float:
        return estimate_cost(
            self.total_prompt_tokens,
            self.total_completion_tokens,
            self.model,
        )

    def summary(self) -> str:
        return (
            f"会话统计 / Session metrics:\n"
            f"  模型 / Model: {self.model or 'unknown'}\n"
            f"  轮次 / Turns: {self.total_turns}\n"
            f"  耗时 / Duration: {self.duration_seconds:.1f}s\n"
            f"  LLM 耗时 / LLM time: {self.total_llm_duration_ms:.0f}ms\n"
            f"  工具调用 / Tool calls: {self.total_tool_calls} "
            f"(errors {self.total_tool_errors}, rate {self.tool_error_rate:.1%})\n"
            f"  Tokens: {self.total_tokens} "
            f"(prompt {self.total_prompt_tokens}, completion {self.total_completion_tokens})\n"
            f"  成本 / Cost: RMB {self.estimated_cost_cny:.4f}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "total_turns": self.total_turns,
            "total_tool_calls": self.total_tool_calls,
            "total_tool_errors": self.total_tool_errors,
            "total_tokens": self.total_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_llm_duration_ms": self.total_llm_duration_ms,
            "duration_seconds": self.duration_seconds,
            "estimated_cost_cny": self.estimated_cost_cny,
            "turns": [
                {
                    "turn": t.turn_number,
                    "llm_duration_ms": t.llm_duration_ms,
                    "tool_calls": t.tool_calls,
                    "tool_results": t.tool_results,
                    "token_prompt": t.token_prompt,
                    "token_completion": t.token_completion,
                }
                for t in self.turns
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_file(self, filepath: str = "") -> str:
        path = filepath or os.path.join(
            os.getcwd(),
            "logs",
            f"session_{time.strftime('%Y%m%d_%H%M%S')}.json",
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_json())
        return path

    @staticmethod
    def from_file(filepath: str) -> "SessionMetrics":
        with open(filepath, encoding="utf-8") as handle:
            data = json.load(handle)
        metrics = SessionMetrics(model=data.get("model", ""))
        metrics.total_turns = data.get("total_turns", 0)
        metrics.total_tool_calls = data.get("total_tool_calls", 0)
        metrics.total_tool_errors = data.get("total_tool_errors", 0)
        metrics.total_prompt_tokens = data.get("total_prompt_tokens", 0)
        metrics.total_completion_tokens = data.get("total_completion_tokens", 0)
        metrics.total_llm_duration_ms = data.get("total_llm_duration_ms", 0.0)
        for turn in data.get("turns", []):
            metrics.turns.append(
                TurnRecord(
                    turn_number=turn["turn"],
                    timestamp=0.0,
                    llm_duration_ms=turn.get("llm_duration_ms", 0.0),
                    tool_calls=turn.get("tool_calls", []),
                    tool_results=turn.get("tool_results", []),
                    token_prompt=turn.get("token_prompt", 0),
                    token_completion=turn.get("token_completion", 0),
                )
            )
        return metrics


class TraceStore:
    """Small in-memory store for the latest session traces."""

    def __init__(self, max_sessions: int = 200):
        self.max_sessions = max_sessions
        self._lock = Lock()
        self._items: dict[str, dict[str, Any]] = {}

    def put(self, trace_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._items[trace_id] = payload
            if len(self._items) > self.max_sessions:
                oldest = sorted(
                    self._items.items(),
                    key=lambda item: item[1].get("updated_at", 0.0),
                )[0][0]
                self._items.pop(oldest, None)

    def get(self, trace_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            payload = self._items.get(trace_id)
            if payload is None:
                return None
            return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


trace_store = TraceStore()


class AgentObserver:
    """
    Observer that captures metrics plus LangGraph-style execution events.
    """

    def __init__(self, model: str = "", session_id: str = ""):
        self.metrics = SessionMetrics(model=model)
        self.trace_id = session_id or uuid.uuid4().hex[:12]
        self._current_turn: Optional[TurnRecord] = None
        self._events: list[TraceEvent] = []
        self._snapshots: list[StateSnapshot] = []
        self._latest_state: Optional[AgentState] = None
        self._latest_status: str = AgentStatus.IDLE.value
        self._updated_at = time.time()

    def _touch(self) -> None:
        self._updated_at = time.time()

    def _snapshot_from_state(self, state: AgentState) -> StateSnapshot:
        last_user = ""
        last_assistant = ""
        for msg in reversed(state.messages):
            if not last_assistant and msg.role.value == "assistant" and msg.content:
                last_assistant = msg.content[:200]
            if not last_user and msg.role.value == "user" and msg.content:
                last_user = msg.content[:200]
            if last_user and last_assistant:
                break
        return StateSnapshot(
            timestamp=time.time(),
            turn=state.turn_count,
            status=state.status.value,
            message_count=len(state.messages),
            tool_calls=len(state.tool_call_history),
            tool_results=len(state.tool_result_history),
            total_tokens=state.token_usage.get("total_tokens", 0),
            last_user_preview=last_user,
            last_assistant_preview=last_assistant,
        )

    def _append_snapshot(self, state: AgentState) -> None:
        self._latest_state = state
        self._latest_status = state.status.value
        self._snapshots.append(self._snapshot_from_state(state))
        if len(self._snapshots) > 200:
            self._snapshots = self._snapshots[-200:]
        self._touch()

    def record_event(
        self,
        *,
        kind: str,
        node: str,
        turn: int = 0,
        status: str = "",
        message: str = "",
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        event = TraceEvent(
            timestamp=time.time(),
            kind=kind,
            node=node,
            turn=turn,
            status=status or self._latest_status,
            message=message,
            payload=payload or {},
        )
        self._events.append(event)
        if len(self._events) > 500:
            self._events = self._events[-500:]
        self._touch()

    def persist(self) -> None:
        trace_store.put(self.trace_id, self.export())

    def export(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "model": self.metrics.model,
            "updated_at": self._updated_at,
            "status": self._latest_status,
            "metrics": self.metrics.to_dict(),
            "events": [asdict(event) for event in self._events],
            "snapshots": [asdict(snapshot) for snapshot in self._snapshots],
        }

    def on_turn_start(self, state: AgentState):
        self._current_turn = TurnRecord(
            turn_number=state.turn_count,
            timestamp=time.monotonic(),
        )
        self._append_snapshot(state)
        self.record_event(
            kind="turn",
            node="turn.start",
            turn=state.turn_count,
            status=state.status.value,
            message=f"Turn {state.turn_count} started",
        )
        logger.info("[%s] Turn %d started", self.trace_id, state.turn_count)

    def on_turn_end(self, state: AgentState):
        self._append_snapshot(state)
        if self._current_turn:
            self.metrics.turns.append(self._current_turn)
            self.metrics.total_turns += 1
            logger.info(
                "[%s] Turn %d finished | LLM %.0fms | tools %s",
                self.trace_id,
                self._current_turn.turn_number,
                self._current_turn.llm_duration_ms,
                ", ".join(self._current_turn.tool_calls) or "(none)",
            )
        self.record_event(
            kind="turn",
            node="turn.end",
            turn=state.turn_count,
            status=state.status.value,
            message=f"Turn {state.turn_count} ended",
            payload={"messages": len(state.messages)},
        )
        self._current_turn = None
        self.persist()

    def on_status_change(self, state: AgentState):
        self._append_snapshot(state)
        self.record_event(
            kind="status",
            node=f"status.{state.status.value}",
            turn=state.turn_count,
            status=state.status.value,
            message=f"Agent status changed to {state.status.value}",
        )

    def on_tool_call(self, tool_call: ToolCall):
        self.metrics.total_tool_calls += 1
        if self._current_turn:
            self._current_turn.tool_calls.append(tool_call.name)
        self.record_event(
            kind="tool",
            node=f"tool.{tool_call.name}",
            turn=self._current_turn.turn_number if self._current_turn else 0,
            status=self._latest_status,
            message=f"Tool call: {tool_call.name}",
            payload={"arguments": tool_call.arguments},
        )
        logger.info(
            "[%s] Tool call: %s(%s)",
            self.trace_id,
            tool_call.name,
            json.dumps(tool_call.arguments, ensure_ascii=False),
        )

    def on_tool_result(self, result: ToolResult):
        if not result.success:
            self.metrics.total_tool_errors += 1
        if self._current_turn:
            status = "OK" if result.success else "FAIL"
            self._current_turn.tool_results.append(
                f"{result.name}: {status} ({result.duration_ms:.0f}ms)"
            )
        self.record_event(
            kind="tool_result",
            node=f"tool.{result.name}.result",
            turn=self._current_turn.turn_number if self._current_turn else 0,
            status="success" if result.success else "failed",
            message=f"Tool result: {result.name}",
            payload={
                "duration_ms": result.duration_ms,
                "success": result.success,
                "error": result.error or "",
                "output_preview": (result.output or "")[:400],
            },
        )
        logger.info(
            "[%s] Tool result: %s -> %s (%.0fms)%s",
            self.trace_id,
            result.name,
            "success" if result.success else "failed",
            result.duration_ms,
            f" - {result.error}" if result.error else "",
        )

    def on_llm_response(self, usage: dict):
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        self.metrics.total_prompt_tokens += prompt
        self.metrics.total_completion_tokens += completion
        if self._current_turn:
            self._current_turn.token_prompt = prompt
            self._current_turn.token_completion = completion
            self._current_turn.llm_duration_ms = (
                time.monotonic() - self._current_turn.timestamp
            ) * 1000
            self.metrics.total_llm_duration_ms += self._current_turn.llm_duration_ms
        self.record_event(
            kind="llm",
            node="llm.response",
            turn=self._current_turn.turn_number if self._current_turn else 0,
            status=self._latest_status,
            message="LLM responded",
            payload={
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": usage.get("total_tokens", prompt + completion),
                "estimated_cost_cny": estimate_cost(prompt, completion, self.metrics.model),
            },
        )
        logger.info(
            "[%s] LLM response | prompt %d | completion %d | cost %.4f",
            self.trace_id,
            prompt,
            completion,
            estimate_cost(prompt, completion, self.metrics.model),
        )

    def on_subagent_event(self, event_name: str, data: dict[str, Any]):
        payload = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        self.record_event(
            kind="subagent",
            node=f"subagent.{event_name}",
            turn=self._current_turn.turn_number if self._current_turn else 0,
            status=self._latest_status,
            message=f"Subagent event: {event_name}",
            payload=payload,
        )
        self.persist()
