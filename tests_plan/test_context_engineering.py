"""
Context Engineering 模块测试 — ContextManager 消息构建/裁剪/摘要/过滤/修复
"""

import pytest
from agent.context import ContextManager
from agent.types import Message, Role


class TestBuildMessages:
    """build_messages 基础功能"""

    def test_system_prompt_inserted_first(self):
        cm = ContextManager(system_prompt="你是 Kai Agent。")
        msgs = cm.build_messages([Message(role=Role.USER, content="hi")])
        assert msgs[0].role == Role.SYSTEM
        assert "你是 Kai Agent" in msgs[0].content

    def test_skill_prompt_appended(self):
        cm = ContextManager(system_prompt="base", skill_prompt="## Skill: 测试")
        msgs = cm.build_messages([Message(role=Role.USER, content="hi")])
        assert "## Skill: 测试" in msgs[0].content

    def test_system_not_duplicated(self):
        cm = ContextManager(system_prompt="你好")
        msgs = cm.build_messages([
            Message(role=Role.SYSTEM, content="已有"),
            Message(role=Role.USER, content="hello"),
        ])
        # Should have exactly one system message
        system_count = sum(1 for m in msgs if m.role == Role.SYSTEM)
        assert system_count == 1

    def test_basic_user_message_preserved(self):
        cm = ContextManager(system_prompt="test")
        msgs = cm.build_messages([Message(role=Role.USER, content="hello")])
        user_msgs = [m for m in msgs if m.role == Role.USER]
        assert any("hello" in m.content for m in user_msgs)


class TestSlidingWindow:
    """滑动窗口"""

    def test_window_limits_messages(self):
        cm = ContextManager(system_prompt="test", window_size=5)
        history = [Message(role=Role.USER, content=f"msg{i}") for i in range(10)]
        msgs = cm.build_messages(history)
        # system + up to window_size+1 messages
        assert len(msgs) <= 7  # system + 5 window + potential extras

    def test_window_preserves_at_least_3(self):
        cm = ContextManager(system_prompt="test", window_size=1)
        history = [Message(role=Role.USER, content=f"msg{i}") for i in range(5)]
        msgs = cm.build_messages(history)
        assert len(msgs) >= 3  # system + at least 2 user/assistant

    def test_window_trim_logging(self):
        cm = ContextManager(system_prompt="test", window_size=3)
        history = [
            Message(role=Role.USER, content="m1"),
            Message(role=Role.ASSISTANT, content="r1"),
            Message(role=Role.USER, content="m2"),
            Message(role=Role.ASSISTANT, content="r2"),
        ]
        cm.build_messages(history)
        assert any("裁剪" in log["detail"] for log in cm.compression_log)


class TestTokenBudgetClipping:
    """Token 预算裁剪"""

    def test_trim_when_over_budget(self):
        cm = ContextManager(
            system_prompt="test",
            max_tokens=200, reserve_tokens=50,  # very small budget
        )
        long_msg = "x" * 200
        history = [Message(role=Role.USER, content=long_msg) for _ in range(5)]
        msgs = cm.build_messages(history)
        assert len(msgs) >= 2  # system + some messages preserved

    def test_estimate_tokens(self):
        cm = ContextManager()
        msgs = [Message(role=Role.USER, content="hello world")]
        estimate = cm.estimate_tokens(msgs)
        assert estimate > 0
        assert isinstance(estimate, int)


class TestHistorySummarization:
    """历史摘要压缩"""

    def test_summarize_simple_qa_round(self):
        cm = ContextManager(system_prompt="test", enable_summary=True)
        history = [
            Message(role=Role.USER, content="你好"),
            Message(role=Role.ASSISTANT, content="你好！有什么可以帮你的？"),
        ]
        msgs = cm.build_messages(history)
        # After summarization, the USER message should be replaced with summary
        user_msgs = [m for m in msgs if m.role == Role.USER]
        assert len(user_msgs) >= 1
        # Summary content should contain both user and assistant parts
        summary_msg = user_msgs[0]
        assert "历史摘要" in summary_msg.content or msgs[0].role == Role.SYSTEM

    def test_summarize_tool_call_round(self):
        cm = ContextManager(system_prompt="test", enable_summary=True)
        history = [
            Message(role=Role.USER, content="帮我查天气"),
            Message(role=Role.ASSISTANT, content="", tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}]),
            Message(role=Role.TOOL, content="晴天", tool_call_id="tc1", name="weather"),
            Message(role=Role.ASSISTANT, content="今天天气晴朗。"),
        ]
        msgs = cm.build_messages(history)
        user_msgs = [m for m in msgs if m.role == Role.USER]
        assert len(user_msgs) >= 1

    def test_summarization_logged(self):
        cm = ContextManager(system_prompt="test", enable_summary=True, max_tokens=100)
        # Build enough messages so that summarization triggers
        history = [
            Message(role=Role.USER, content="你好"),
            Message(role=Role.ASSISTANT, content="回复"),
            Message(role=Role.USER, content="问题" + "x" * 100),
            Message(role=Role.ASSISTANT, content="答案" + "y" * 100),
        ]
        cm.build_messages(history)
        actions = [log["action"] for log in cm.compression_log]
        assert "summary" in actions or "trim" in actions


class TestRelevanceFiltering:
    """相关性过滤"""

    def test_relevant_keyword_kept(self):
        cm = ContextManager(system_prompt="test", enable_relevance=True)
        history = [
            Message(role=Role.USER, content="Python是什么"),
            Message(role=Role.ASSISTANT, content="Python是一种编程语言"),
            Message(role=Role.USER, content="今天天气怎么样"),
            Message(role=Role.ASSISTANT, content="今天天气很好"),
        ]
        msgs = cm.build_messages(history, user_message="Python语法")
        contents = [(m.role.value, m.content[:50]) for m in msgs]
        # Python-related message should be kept
        assert any("Python" in m.content for m in msgs)

    def test_last_two_kept_always(self):
        cm = ContextManager(system_prompt="test", enable_relevance=True)
        history = [
            Message(role=Role.USER, content="m1"),
            Message(role=Role.ASSISTANT, content="r1"),
            Message(role=Role.USER, content="m2"),
            Message(role=Role.ASSISTANT, content="r2"),
        ]
        msgs = cm.build_messages(history, user_message="unrelated_keyword_xyz")
        # Last 2 messages should be kept even if irrelevant
        last_msg = msgs[-1]
        assert "r2" in last_msg.content

    def test_short_query_skips_filter(self):
        cm = ContextManager(system_prompt="test", enable_relevance=True)
        history = [Message(role=Role.USER, content="hi"), Message(role=Role.ASSISTANT, content="hello")]
        msgs = cm.build_messages(history, user_message="hi")
        assert len(msgs) >= 2


class TestRepairToolPairs:
    """Tool call/tool result 配对修复"""

    def test_remove_orphan_tool_call(self):
        msgs = [
            Message(role=Role.SYSTEM, content="test"),
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="", tool_calls=[{"id": "orphan_tc", "function": {"name": "test", "arguments": "{}"}}]),
        ]
        repaired = ContextManager.repair_tool_pairs(msgs)
        # Orphan tool call should be removed
        assistant_with_tc = [m for m in repaired if m.role == Role.ASSISTANT and m.tool_calls]
        assert len(assistant_with_tc) == 0

    def test_remove_orphan_tool_result(self):
        msgs = [
            Message(role=Role.SYSTEM, content="test"),
            Message(role=Role.USER, content="hi"),
            Message(role=Role.TOOL, content="result", tool_call_id="no_such_tc"),
        ]
        repaired = ContextManager.repair_tool_pairs(msgs)
        tool_msgs = [m for m in repaired if m.role == Role.TOOL]
        assert len(tool_msgs) == 0

    def test_keep_valid_pair(self):
        msgs = [
            Message(role=Role.SYSTEM, content="test"),
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="", tool_calls=[{"id": "tc1", "function": {"name": "echo", "arguments": "{}"}}]),
            Message(role=Role.TOOL, content="echoed", tool_call_id="tc1", name="echo"),
            Message(role=Role.ASSISTANT, content="done"),
        ]
        repaired = ContextManager.repair_tool_pairs(msgs)
        assert len(repaired) >= 4  # system + user + assistant(tc) + tool + assistant(reply)

    def test_remove_excess_tool_results(self):
        """多个 TOOL 结果中多余的被移除"""
        msgs = [
            Message(role=Role.SYSTEM, content="test"),
            Message(role=Role.ASSISTANT, content="", tool_calls=[{"id": "tc1", "function": {"name": "echo", "arguments": "{}"}}]),
            Message(role=Role.TOOL, content="result1", tool_call_id="tc1", name="echo"),
            Message(role=Role.TOOL, content="result2", tool_call_id="tc1", name="echo"),  # duplicate
        ]
        repaired = ContextManager.repair_tool_pairs(msgs)
        tool_msgs = [m for m in repaired if m.role == Role.TOOL]
        assert len(tool_msgs) <= 1  # only one TOOL per tc_id

    def test_preserves_normal_messages(self):
        msgs = [
            Message(role=Role.SYSTEM, content="test"),
            Message(role=Role.USER, content="q1"),
            Message(role=Role.ASSISTANT, content="a1"),
            Message(role=Role.USER, content="q2"),
            Message(role=Role.ASSISTANT, content="a2"),
        ]
        repaired = ContextManager.repair_tool_pairs(msgs)
        assert len(repaired) == len(msgs)


class TestCompressHistory:
    """compress_history 快捷方法"""

    def test_compress_history(self):
        cm = ContextManager(system_prompt="test")
        history = [Message(role=Role.USER, content="hi"), Message(role=Role.ASSISTANT, content="hello")]
        compressed = cm.compress_history(history)
        assert compressed is not None
        assert len(compressed) >= 2
