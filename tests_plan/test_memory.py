"""
Memory 模块测试 — MemoryStore + ConversationStore
"""

import pytest
import time


class TestMemoryStore:
    """MemoryStore CRUD + 搜索 + 上下文注入"""

    def test_save_and_get(self, temp_memory_store):
        m = temp_memory_store
        m.save("user_name", "张三", type="fact", tags=["identity"])
        got = m.get("user_name")
        assert got is not None
        assert got["content"] == "张三"
        assert got["type"] == "fact"
        assert "identity" in got["tags"]

    def test_save_overwrite(self, temp_memory_store):
        m = temp_memory_store
        m.save("key1", "old")
        m.save("key1", "new")
        got = m.get("key1")
        assert got["content"] == "new"

    def test_get_nonexistent_returns_none(self, temp_memory_store):
        assert temp_memory_store.get("nothing") is None

    def test_search_by_keyword(self, temp_memory_store):
        m = temp_memory_store
        m.save("pref_lang", "Python")
        m.save("hobby", "绘画")
        results = m.search("Python")
        assert len(results) >= 1
        assert any("Python" in r["content"] for r in results)

    def test_search_with_type_filter(self, temp_memory_store):
        m = temp_memory_store
        m.save("fact_a", "内容A", type="fact")
        m.save("pref_b", "内容B", type="preference")
        results = m.search("内容", type="fact")
        assert all(r["type"] == "fact" for r in results)

    def test_delete(self, temp_memory_store):
        m = temp_memory_store
        m.save("del_me", "to be deleted")
        assert m.delete("del_me") is True
        assert m.get("del_me") is None
        assert m.delete("nonexistent") is False

    def test_list_all(self, temp_memory_store):
        m = temp_memory_store
        m.save("a", "1", type="fact")
        m.save("b", "2", type="preference")
        all_items = m.list_all(limit=10)
        assert len(all_items) >= 2

    def test_get_relevant_context(self, temp_memory_store):
        m = temp_memory_store
        m.save("lang", "I love Python")
        context = m.get_relevant_context("Python", max_items=5)
        assert "## 长期记忆" in context
        assert "Python" in context

    def test_get_relevant_context_empty(self, temp_memory_store):
        context = temp_memory_store.get_relevant_context("nothing here")
        assert context == ""


class TestConversationStore:
    """ConversationStore 会话 + 消息管理"""

    def test_create_session(self, temp_conversation_store):
        cs = temp_conversation_store
        result = cs.create_session("sess_1", "测试会话")
        assert result["id"] == "sess_1"

    def test_list_sessions(self, temp_conversation_store):
        cs = temp_conversation_store
        cs.create_session("s1", "会话1")
        cs.create_session("s2", "会话2")
        sessions = cs.list_sessions()
        assert len(sessions) >= 2
        ids = [s["id"] for s in sessions]
        assert "s1" in ids and "s2" in ids

    def test_rename_session(self, temp_conversation_store):
        cs = temp_conversation_store
        cs.create_session("s_rename", "原名")
        assert cs.rename_session("s_rename", "新名") is True

    def test_delete_session(self, temp_conversation_store):
        cs = temp_conversation_store
        cs.create_session("s_del", "待删除")
        cs.delete_session("s_del")
        ids = [s["id"] for s in cs.list_sessions()]
        assert "s_del" not in ids

    def test_save_and_get_messages(self, temp_conversation_store):
        cs = temp_conversation_store
        cs.create_session("s_msg")
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        cs.save_messages("s_msg", msgs)
        retrieved = cs.get_messages("s_msg")
        assert len(retrieved) == 2
        assert retrieved[0]["content"] == "你好"

    def test_get_messages_empty_session(self, temp_conversation_store):
        cs = temp_conversation_store
        cs.create_session("s_empty")
        assert cs.get_messages("s_empty") == []

    def test_clear_session_messages(self, temp_conversation_store):
        cs = temp_conversation_store
        cs.create_session("s_clr")
        cs.save_messages("s_clr", [{"role": "user", "content": "hi"}])
        cs.clear_session_messages("s_clr")
        assert cs.get_messages("s_clr") == []

    def test_msgs_to_history(self):
        from memory.conversation_store import msgs_to_history
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮你的？"},
            {"role": "tool", "content": "result"},
        ]
        history = msgs_to_history(msgs)
        assert "## 历史对话" in history
        assert "[user]" in history
        assert "[assistant]" in history
        assert "[tool]" not in history  # tool 消息被过滤

    def test_msgs_to_history_empty(self):
        from memory.conversation_store import msgs_to_history
        assert msgs_to_history([]) == ""
