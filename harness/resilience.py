"""
Resilience helpers for retry and circuit-breaking around LLM calls.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("harness.resilience")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Shared circuit breaker protecting upstream LLM calls.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        half_open_max_calls: int = 1,
        half_open_success_threshold: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = max(1, half_open_max_calls)
        self.half_open_success_threshold = max(1, half_open_success_threshold)
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float = 0.0
        self._half_open_in_flight = 0
        self._half_open_successes = 0

    @property
    def is_open(self) -> bool:
        return not self.allow_request()

    def allow_request(self) -> bool:
        now = time.monotonic()
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if now - self._opened_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                self._half_open_in_flight = 0
                self._half_open_successes = 0
                logger.info("Circuit breaker entering half-open state")
            else:
                return False
        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_in_flight >= self.half_open_max_calls:
                return False
            self._half_open_in_flight += 1
        return True

    def record_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_success_threshold:
                self.state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_successes = 0
                logger.info("Circuit breaker closed after successful probe")
            return
        self._failure_count = 0

    def record_failure(self):
        if self.state == CircuitState.HALF_OPEN:
            self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
            self._trip_open()
            return
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._trip_open()

    def _trip_open(self):
        self.state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._half_open_in_flight = 0
        self._half_open_successes = 0
        logger.warning(
            "Circuit breaker opened after %s failures; cooldown %.1fs",
            self._failure_count,
            self.cooldown_seconds,
        )


_BREAKER_REGISTRY: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    cooldown_seconds: float = 30.0,
    half_open_max_calls: int = 1,
    half_open_success_threshold: int = 1,
) -> CircuitBreaker:
    breaker = _BREAKER_REGISTRY.get(name)
    if breaker is None:
        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            half_open_max_calls=half_open_max_calls,
            half_open_success_threshold=half_open_success_threshold,
        )
        _BREAKER_REGISTRY[name] = breaker
    return breaker


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    retryable_exceptions: tuple = (Exception,)
    should_retry_result: Optional[Callable[[Any], bool]] = None
    get_delay_for_result: Optional[Callable[[Any, int], Optional[float]]] = None


async def retry_with_backoff(
    fn: Callable[..., Awaitable],
    *args,
    config: RetryConfig = None,
    **kwargs,
):
    cfg = config or RetryConfig()
    last_exception = None
    last_result = None

    for attempt in range(cfg.max_retries + 1):
        try:
            result = await fn(*args, **kwargs)
            last_result = result
            if not cfg.should_retry_result or not cfg.should_retry_result(result):
                return result
            if attempt < cfg.max_retries:
                delay = _compute_result_delay(cfg, result, attempt)
                logger.warning(
                    "Retrying result %s/%s in %.1fs",
                    attempt + 1,
                    cfg.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            logger.error("Retry budget exhausted after %s result retries", cfg.max_retries)
            return result
        except cfg.retryable_exceptions as e:
            last_exception = e
            if attempt < cfg.max_retries:
                delay = _compute_backoff_delay(cfg, attempt)
                logger.warning(
                    "Retrying exception %s/%s in %.1fs: %s",
                    attempt + 1,
                    cfg.max_retries,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("Retry budget exhausted after %s exceptions: %s", cfg.max_retries, e)

    if last_exception is not None:
        raise last_exception
    return last_result


def _compute_backoff_delay(cfg: RetryConfig, attempt: int) -> float:
    return min(
        cfg.base_delay * (cfg.backoff_multiplier ** attempt),
        cfg.max_delay,
    )


def _compute_result_delay(cfg: RetryConfig, result: Any, attempt: int) -> float:
    if cfg.get_delay_for_result:
        delay = cfg.get_delay_for_result(result, attempt)
        if delay is not None:
            return min(delay, cfg.max_delay)
    return _compute_backoff_delay(cfg, attempt)
