"""
Observability 模块测试 — SessionMetrics + AgentObserver + cost estimation
"""

import json
import pytest
import time
import tempfile
import os

from harness.observability import (
    estimate_cost,
    SessionMetrics,
    TurnRecord,
    AgentObserver,
    MODEL_PRICING,
)
from agent.types import ToolCall, ToolResult, AgentState, AgentStatus


class TestEstimateCost:
    """成本估算"""

    def test_deepseek_v4_flash_pricing(self):
        cost = estimate_cost(1_000_000, 0, "deepseek-v4-flash")
        assert cost == 1.0  # ¥1 per 1M input tokens

    def test_deepseek_v4_flash_output(self):
        cost = estimate_cost(0, 1_000_000, "deepseek-v4-flash")
        assert cost == 2.0  # ¥2 per 1M output tokens

    def test_mixed_tokens(self):
        cost = estimate_cost(500_000, 250_000, "deepseek-v4-flash")
        assert cost == 0.5 + 0.5  # 0.5 input + 0.5 output

    def test_fallback_pricing(self):
        cost = estimate_cost(1_000_000, 1_000_000, "unknown-model")
        assert cost == 3.0 + 6.0  # DEFAULT_PRICE

    def test_zero_tokens(self):
        cost = estimate_cost(0, 0, "deepseek-v4-flash")
        assert cost == 0.0


class TestSessionMetrics:
    """会话级指标"""

    def test_total_tokens_property(self):
        m = SessionMetrics()
        m.total_prompt_tokens = 100
        m.total_completion_tokens = 50
        assert m.total_tokens == 150

    def test_duration_seconds(self):
        m = SessionMetrics()
        assert m.duration_seconds >= 0

    def test_tool_error_rate(self):
        m = SessionMetrics()
        m.total_tool_calls = 10
        m.total_tool_errors = 3
        assert m.tool_error_rate == 0.3

    def test_tool_error_rate_no_calls(self):
        m = SessionMetrics()
        assert m.tool_error_rate == 0.0

    def test_estimated_cost_cny(self):
        m = SessionMetrics(model="deepseek-v4-flash")
        m.total_prompt_tokens = 1_000_000
        m.total_completion_tokens = 500_000
        assert m.estimated_cost_cny == 1.0 + 1.0  # 1 input + 1 output

    def test_summary_contains_fields(self):
        m = SessionMetrics(model="deepseek-v4-flash")
        m.total_turns = 5
        m.total_tool_calls = 12
        summary = m.summary()
        assert "模型:" in summary or "模型" in summary
        assert "5" in summary

    def test_to_json(self):
        m = SessionMetrics(model="test-model")
        m.total_turns = 3
        json_str = m.to_json()
        data = json.loads(json_str)
        assert data["model"] == "test-model"
        assert data["total_turns"] == 3

    def test_to_file_and_from_file(self):
        m = SessionMetrics(model="test-model")
        m.total_turns = 2
        m.total_tool_calls = 5
        m.total_prompt_tokens = 100
        m.total_completion_tokens = 50

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name

        try:
            m.to_file(path)
            restored = SessionMetrics.from_file(path)
            assert restored.total_turns == 2
            assert restored.total_tool_calls == 5
            assert restored.total_prompt_tokens == 100
            assert restored.total_completion_tokens == 50
        finally:
            os.unlink(path)

    def test_to_dict_contains_metrics(self):
        m = SessionMetrics(model="m1")
        m.total_turns = 1
        d = m.to_dict()
        assert d["model"] == "m1"
        assert d["total_turns"] == 1
        assert "estimated_cost_cny" in d


class TestAgentObserver:
    """Agent 观测器钩子"""

    def setup_method(self):
        self.observer = AgentObserver(model="deepseek-v4-flash")

    def test_on_turn_start_creates_record(self):
        state = AgentState()
        state.turn_count = 1
        self.observer.on_turn_start(state)
        assert self.observer._current_turn is not None
        assert self.observer._current_turn.turn_number == 1

    def test_on_turn_end_appends_record(self):
        state = AgentState()
        state.turn_count = 1
        self.observer.on_turn_start(state)
        self.observer.on_turn_end(state)
        assert len(self.observer.metrics.turns) == 1
        assert self.observer.metrics.total_turns == 1

    def test_on_tool_call_increments(self):
        tc = ToolCall(id="c1", name="bash", arguments={"command": "ls"})
        self.observer.on_tool_call(tc)
        assert self.observer.metrics.total_tool_calls == 1

    def test_on_tool_call_adds_to_current_turn(self):
        state = AgentState()
        state.turn_count = 1
        self.observer.on_turn_start(state)
        tc = ToolCall(id="c1", name="echo", arguments={"text": "hi"})
        self.observer.on_tool_call(tc)
        assert "echo" in self.observer._current_turn.tool_calls

    def test_on_tool_result_success(self):
        tr = ToolResult(tool_call_id="c1", name="echo", success=True, output="hi")
        self.observer.on_tool_result(tr)
        assert self.observer.metrics.total_tool_errors == 0

    def test_on_tool_result_failure(self):
        tr = ToolResult(tool_call_id="c1", name="bash", success=False, output="", error="failed")
        self.observer.on_tool_result(tr)
        assert self.observer.metrics.total_tool_errors == 1

    def test_on_llm_response_updates_tokens(self):
        state = AgentState()
        state.turn_count = 1
        self.observer.on_turn_start(state)
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        self.observer.on_llm_response(usage)
        assert self.observer.metrics.total_prompt_tokens == 100
        assert self.observer.metrics.total_completion_tokens == 50

    def test_on_llm_response_sets_llm_duration(self):
        state = AgentState()
        state.turn_count = 1
        import time
        self.observer.on_turn_start(state)
        time.sleep(0.01)  # ensure measurable delay
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        self.observer.on_llm_response(usage)
        assert self.observer._current_turn.llm_duration_ms >= 0

    def test_on_status_change_records_event(self):
        state = AgentState()
        state.turn_count = 2
        state.status = AgentStatus.THINKING
        self.observer.on_status_change(state)
        exported = self.observer.export()
        assert exported["events"][-1]["kind"] == "status"
        assert exported["events"][-1]["status"] == AgentStatus.THINKING.value

    def test_on_subagent_event_records_trace(self):
        self.observer.on_subagent_event("subtask_done", {"id": "1", "status": "success"})
        exported = self.observer.export()
        assert exported["events"][-1]["kind"] == "subagent"
        assert exported["events"][-1]["node"] == "subagent.subtask_done"

    def test_export_contains_snapshots(self):
        state = AgentState()
        state.turn_count = 1
        state.status = AgentStatus.THINKING
        self.observer.on_turn_start(state)
        exported = self.observer.export()
        assert exported["trace_id"] == self.observer.trace_id
        assert len(exported["snapshots"]) >= 1
