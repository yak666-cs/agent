"""
Resilience 模块 —— Agent Loop 的容错机制

三个核心机制：

1. Retry（重试）：
   - LLM 调用失败（网络抖动、429 限流）→ 指数退避重试
   - 工具执行失败 → 不作为重试（工具错误应该让 LLM 自行调整）

2. Circuit Breaker（熔断）：
   - 连续 N 次失败 → 暂停一段时间 → 半开尝试 → 恢复或继续熔断
   - 防止在 LLM API 不可用时反复尝试浪费资源

3. Graceful Degradation（优雅降级）：
   - 某个 Skill 不可用时 → 告知 LLM 该工具不可用，尝试替代方案
"""

import asyncio
import time
import logging
from enum import Enum
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("harness.resilience")


class CircuitState(str, Enum):
    CLOSED = "closed"             # 正常
    OPEN = "open"                 # 熔断中
    HALF_OPEN = "half_open"       # 半开（探测中）


class CircuitBreaker:
    """
    熔断器 —— 保护 Agent Loop 不被不可用的 LLM API 拖垮

    状态转换：
        CLOSED ──(连续失败>阈值)──→ OPEN
        OPEN   ──(冷却时间到)────→ HALF_OPEN
        HALF_OPEN ──(成功)───────→ CLOSED
        HALF_OPEN ──(失败)───────→ OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._opened_at: float = 0

    @property
    def is_open(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return False
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                logger.info("熔断器进入半开状态，尝试探测...")
                return False
            return True
        return False  # HALF_OPEN

    def record_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info("熔断器恢复关闭状态")
        self._failure_count = 0

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                f"熔断器打开！连续 {self._failure_count} 次失败，"
                f"冷却 {self.cooldown_seconds}s"
            )


class RetryConfig:
    """重试配置"""
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_multiplier: float = 2.0,
        retryable_exceptions: tuple = (Exception,),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.retryable_exceptions = retryable_exceptions


async def retry_with_backoff(
    fn: Callable[..., Awaitable],
    *args,
    config: RetryConfig = None,
    **kwargs,
):
    """
    带指数退避的重试包装器。

    用法:
        result = await retry_with_backoff(llm.chat, messages, tools=tools)
    """
    cfg = config or RetryConfig()
    last_exception = None

    for attempt in range(cfg.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except cfg.retryable_exceptions as e:
            last_exception = e
            if attempt < cfg.max_retries:
                delay = min(
                    cfg.base_delay * (cfg.backoff_multiplier ** attempt),
                    cfg.max_delay,
                )
                logger.warning(
                    f"重试 {attempt+1}/{cfg.max_retries}，"
                    f"{delay:.1f}s 后重试: {e}"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"重试耗尽 ({cfg.max_retries}): {e}")

    raise last_exception
