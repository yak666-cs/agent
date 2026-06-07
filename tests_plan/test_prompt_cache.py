"""
Prompt Cache 模块测试 — PromptCache 分层缓存
"""

import time
import pytest
from tools.prompt_cache import PromptCache, CacheStats


class TestCacheStats:
    """缓存统计"""

    def test_hit_rate_zero_when_no_requests(self):
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate_calculation(self):
        s = CacheStats()
        s.hits = 3
        s.misses = 1
        assert s.hit_rate == 0.75

    def test_summary_contains_stats(self):
        s = CacheStats()
        s.hits = 5
        s.misses = 5
        s.disk_hits = 2
        s.total_saved_tokens = 1000
        s.total_saved_ms = 500.0
        summary = s.summary()
        assert "50.0%" in summary or "50" in summary
        assert "1,000" in summary or "1000" in summary


class TestPromptCacheMakeKey:
    """缓存 key 生成"""

    def test_same_inputs_same_key(self):
        from agent.types import Message, Role
        msgs1 = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="Hello"),
        ]
        msgs2 = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="Hello"),
        ]
        assert PromptCache.make_key(msgs1) == PromptCache.make_key(msgs2)

    def test_different_inputs_different_key(self):
        from agent.types import Message, Role
        msgs1 = [Message(role=Role.USER, content="Hello")]
        msgs2 = [Message(role=Role.USER, content="World")]
        assert PromptCache.make_key(msgs1) != PromptCache.make_key(msgs2)

    def test_key_includes_tool_count(self):
        from agent.types import Message, Role
        msgs = [Message(role=Role.USER, content="Hi")]
        key_no_tools = PromptCache.make_key(msgs)
        key_with_tools = PromptCache.make_key(msgs, tools=[{"type": "function", "function": {"name": "echo"}}])
        assert key_no_tools != key_with_tools

    def test_system_prompt_key(self):
        key1 = PromptCache.system_prompt_key("You are helpful.")
        key2 = PromptCache.system_prompt_key("You are helpful.")
        key3 = PromptCache.system_prompt_key("You are evil.")
        assert key1 == key2
        assert key1 != key3


class TestPromptCacheL1:
    """L1 内存缓存"""

    def test_set_and_get(self):
        cache = PromptCache(l1_ttl=30.0, l2_ttl=0)  # l2_ttl=0 disables L2 effectively
        key = "test_key"
        cache.set(key, "hello world", [], "stop")
        result = cache.get(key)
        assert result is not None
        content, tool_calls, finish_reason = result
        assert content == "hello world"
        assert finish_reason == "stop"

    def test_miss_returns_none(self):
        cache = PromptCache(l1_ttl=30.0)
        assert cache.get("nonexistent") is None

    def test_expired_l1_returns_none(self):
        cache = PromptCache(l1_ttl=-1.0, l2_ttl=0)  # negative TTL = immediately expired
        cache.set("exp_key", "data", [], "stop")
        # L1 expired — should miss
        result = cache.get("exp_key")
        assert result is None

    def test_l1_eviction(self):
        cache = PromptCache(l1_ttl=30.0, max_l1_entries=2, l2_ttl=0)
        cache.set("k1", "v1", [], "stop")
        cache.set("k2", "v2", [], "stop")
        cache.set("k3", "v3", [], "stop")
        assert cache.get("k1") is None  # should be evicted
        assert cache.get("k2") is not None
        assert cache.get("k3") is not None

    def test_hit_increments_stats(self):
        cache = PromptCache(l1_ttl=30.0, l2_ttl=0)
        key = "stat_test"
        cache.set(key, "data", [], "stop")
        before = cache.stats.hits
        cache.get(key)
        assert cache.stats.hits == before + 1


class TestPromptCacheL2:
    """L2 磁盘缓存"""

    def test_l2_hit_fills_l1(self, tmp_path):
        cache = PromptCache(l1_ttl=30.0, l2_ttl=300.0, disk_dir=str(tmp_path))
        key = "l2_test"
        cache.set(key, "disk_data", [], "stop")
        # 清除 L1
        cache._l1.clear()
        result = cache.get(key)
        assert result is not None
        content, _, _ = result
        assert content == "disk_data"

    def test_l2_expired_returns_none(self, tmp_path):
        cache = PromptCache(l1_ttl=30.0, l2_ttl=-1.0, disk_dir=str(tmp_path))
        key = "l2_expired"
        cache.set(key, "data", [], "stop")
        cache._l1.clear()
        result = cache.get(key)
        assert result is None


class TestPromptCacheInvalidate:
    """缓存失效"""

    def test_invalidate_all_l1(self):
        cache = PromptCache(l1_ttl=30.0, l2_ttl=0)
        cache.set("a", "1", [], "stop")
        cache.set("b", "2", [], "stop")
        cache.invalidate()
        assert len(cache._l1) == 0

    def test_invalidate_by_prefix(self):
        cache = PromptCache(l1_ttl=30.0, l2_ttl=0)
        cache.set("user:1", "data1", [], "stop")
        cache.set("user:2", "data2", [], "stop")
        cache.set("sys:1", "data3", [], "stop")
        cache.invalidate("user:")
        assert "user:1" not in cache._l1
        assert "user:2" not in cache._l1
        assert "sys:1" in cache._l1

    def test_clear(self, tmp_path):
        cache = PromptCache(disk_dir=str(tmp_path))
        cache.set("clr_key", "data", [], "stop")
        cache.clear()
        assert len(cache._l1) == 0
        assert list(tmp_path.glob("*.json")) == []
