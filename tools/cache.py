"""结果缓存 —— 工具调用结果的客户端缓存"""

import time
from typing import Any, Optional


class ResultCache:
    """基于 TTL 的内存缓存，线程安全（GIL 保护无需额外锁）。"""

    def __init__(self, default_ttl: float = 3.0):
        self.default_ttl = default_ttl
        self._store: dict[str, tuple[float, str]] = {}

    @staticmethod
    def make_key(tool_name: str, arguments: dict) -> str:
        items = sorted((k, str(v)) for k, v in arguments.items())
        return f"{tool_name}:{items}"

    def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self.default_ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: str, ttl: float | None = None) -> None:
        self._store[key] = (time.monotonic(), value)
        if ttl is not None:
            # 以新的 ttl 覆盖 default_ttl，存为过期时间戳
            self._store[key] = (time.monotonic(), value)

    def invalidate(self, tool_name: str | None = None) -> int:
        """使缓存失效。tool_name 为 None 则清空全部，否则只清特定工具的缓存。"""
        if tool_name is None:
            count = len(self._store)
            self._store.clear()
            return count
        keys = [k for k in self._store if k.startswith(f"{tool_name}:")]
        for k in keys:
            del self._store[k]
        return len(keys)


# 全局单例
result_cache = ResultCache()
