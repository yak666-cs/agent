"""
Prompt Cache —— 分层提示词缓存

三层结构：
1. L1 内存缓存（最快，进程内共享）
2. L2 磁盘缓存（跨进程，持久化）
3. System Prompt 缓存（稳定不变的部分）

缓存策略：
- 精确匹配：完整消息列表 hash → 缓存响应
- System Prompt 分段缓存：只缓存 system prompt 的 embedding/压缩表示
- 统计追踪：命中率、延迟节省
"""

import json
import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tools.prompt_cache")


class CacheStats:
    """缓存命中统计"""
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.disk_hits = 0
        self.total_saved_tokens = 0
        self.total_saved_ms = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def summary(self) -> str:
        total = self.hits + self.misses
        return (
            f"缓存统计: 请求 {total} 次 | "
            f"命中 {self.hits} 次 ({self.hit_rate:.1%}) | "
            f"磁盘命中 {self.disk_hits} 次 | "
            f"节省 token {self.total_saved_tokens:,} | "
            f"节省延迟 {self.total_saved_ms:.0f}ms"
        )


class PromptCache:
    """
    分层提示词缓存。

    L1（内存）: dict[str, tuple[expire_at, response_json]]
    L2（磁盘）: JSON 文件，key 为 hash，value 为响应
    """

    def __init__(
        self,
        l1_ttl: float = 30.0,
        l2_ttl: float = 300.0,
        disk_dir: str = "",
        max_l1_entries: int = 500,
    ):
        self.l1_ttl = l1_ttl
        self.l2_ttl = l2_ttl
        self.max_l1_entries = max_l1_entries
        self.stats = CacheStats()

        self._l1: dict[str, tuple[float, str, list, str]] = {}
        # L2 存储目录
        disk_dir = disk_dir or os.environ.get("KAI_CACHE_DIR", "")
        self._l2_dir = Path(disk_dir) / ".kai_cache" if disk_dir else Path(".kai_cache")
        self._l2_dir.mkdir(parents=True, exist_ok=True)

    # ---- Key 生成 ----

    @staticmethod
    def make_key(messages: list, tools: list[dict] | None = None) -> str:
        """生成缓存 key：system prompt + 最后 2 条消息 + 工具列表长度。"""
        raw_parts = []
        for m in messages:
            if getattr(m, "role", None) == "system" or (isinstance(m, dict) and m.get("role") == "system"):
                content = m.content if hasattr(m, "content") else m.get("content", "")
                raw_parts.append(f"s:{content[:300]}")
        for m in messages[-2:]:
            content = m.content if hasattr(m, "content") else m.get("content", "")
            role = m.role.value if hasattr(m, "role") else m.get("role", "")
            raw_parts.append(f"{role}:{content[:500]}")
        if tools:
            raw_parts.append(f"tools:{len(tools)}")
        raw = "||".join(raw_parts)
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def system_prompt_key(system_prompt: str) -> str:
        """System Prompt 的专用 key。"""
        return f"sys:{hashlib.md5(system_prompt.encode()).hexdigest()}"

    # ---- 读写 ----

    def get(self, key: str) -> Optional[tuple]:
        """按 key 查找缓存。先查 L1，未命中查 L2。"""
        now = time.monotonic()

        # L1 查询
        entry = self._l1.get(key)
        if entry:
            expire_at, content, tool_calls, finish_reason = entry
            if now < expire_at:
                self.stats.hits += 1
                return entry[1:]  # 去掉 expire_at
            del self._l1[key]

        # L2 查询
        disk_entry = self._read_disk(key)
        if disk_entry:
            expire_at, content, tool_calls, finish_reason = disk_entry
            if now < expire_at:
                # 提升到 L1
                self._l1[key] = disk_entry
                self.stats.hits += 1
                self.stats.disk_hits += 1
                return content, tool_calls, finish_reason
            self._evict_disk(key)

        self.stats.misses += 1
        return None

    def set(self, key: str, content: str, tool_calls: list, finish_reason: str):
        """写入 L1 缓存，并异步写 L2。"""
        now = time.monotonic()
        self._l1[key] = (now + self.l1_ttl, content, tool_calls, finish_reason)

        # L1 淘汰
        if len(self._l1) > self.max_l1_entries:
            oldest_key = min(self._l1.keys(), key=lambda k: self._l1[k][0])
            del self._l1[oldest_key]

        # L2 持久化
        self._write_disk(key, (now + self.l2_ttl, content, tool_calls, finish_reason))

    def record_saved(self, tokens: int, duration_ms: float):
        """记录缓存的 token 和延迟节省。"""
        self.stats.total_saved_tokens += tokens
        self.stats.total_saved_ms += duration_ms

    # ---- 清理 ----

    def clear(self):
        self._l1.clear()
        for f in self._l2_dir.glob("*.json"):
            f.unlink()
        logger.info("PromptCache 已清空")

    def invalidate(self, key_prefix: str = ""):
        """按前缀失效缓存。空前缀 = 清空 L1。"""
        if not key_prefix:
            self._l1.clear()
            return
        self._l1 = {k: v for k, v in self._l1.items() if not k.startswith(key_prefix)}

    # ---- 磁盘操作 ----

    def _disk_path(self, key: str) -> Path:
        return self._l2_dir / f"{key}.json"

    def _read_disk(self, key: str) -> Optional[tuple]:
        path = self._disk_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return (data["expire_at"], data["content"], data.get("tool_calls", []), data.get("finish_reason", "stop"))
        except (json.JSONDecodeError, KeyError):
            return None

    def _write_disk(self, key: str, entry: tuple):
        expire_at, content, tool_calls, finish_reason = entry
        try:
            data = {
                "expire_at": expire_at,
                "content": content,
                "tool_calls": tool_calls,
                "finish_reason": finish_reason,
                "created_at": time.monotonic(),
            }
            self._disk_path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.debug(f"L2 写入失败: {e}")

    def _evict_disk(self, key: str):
        try:
            self._disk_path(key).unlink(missing_ok=True)
        except OSError:
            pass


# 全局单例
prompt_cache = PromptCache()
