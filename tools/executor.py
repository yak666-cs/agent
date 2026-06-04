"""
Tool 执行器 —— 工具调用的执行边界

和原来的 SkillExecutor 一样，职责不变：
超时控制 + 输出截断 + 异常捕获

增强：集成结果缓存，对 READ_ONLY 工具自动缓存结果。
"""

import asyncio
import time
import logging
from agent.types import ToolCall, ToolResult
from .cache import result_cache

logger = logging.getLogger("agent.tools.executor")

MAX_OUTPUT_CHARS = 8_000


class ToolExecutor:
    def __init__(self, default_timeout: float = 30.0, max_output_chars: int = MAX_OUTPUT_CHARS):
        self.default_timeout = default_timeout
        self.max_output_chars = max_output_chars

    async def execute(self, tool_call: ToolCall, tool) -> ToolResult:
        timeout = getattr(tool.meta, "timeout_seconds", self.default_timeout)
        start = time.monotonic()

        # ── 缓存命中直接返回 ──
        cache_ttl = getattr(tool.meta, "cache_ttl", 0.0)
        if cache_ttl > 0:
            key = result_cache.make_key(tool_call.name, tool_call.arguments)
            cached = result_cache.get(key)
            if cached is not None:
                duration_ms = (time.monotonic() - start) * 1000
                return ToolResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    success=True, output=f"[缓存] {tool_call.name} 结果（{duration_ms:.0f}ms）\n\n{cached}",
                    duration_ms=duration_ms,
                )

        try:
            output = await asyncio.wait_for(
                tool.execute(**tool_call.arguments),
                timeout=timeout,
            )
            output = str(output) if output is not None else ""
            if len(output) > self.max_output_chars:
                output = (
                    output[:self.max_output_chars]
                    + f"\n\n[输出被截断，原长度 {len(output)} 字符，已省略 {len(output) - self.max_output_chars} 字符]"
                )
            duration_ms = (time.monotonic() - start) * 1000

            # ── 缓存结果 ──
            if cache_ttl > 0:
                key = result_cache.make_key(tool_call.name, tool_call.arguments)
                result_cache.set(key, output, ttl=cache_ttl)

            return ToolResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                success=True, output=output, duration_ms=duration_ms,
            )
        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                success=False, output="",
                error=f"执行超时（{timeout} 秒）", duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                success=False, output="",
                error=f"{type(e).__name__}: {str(e)}", duration_ms=duration_ms,
            )
