"""通用速率限制器（对标 ViMax rate_limiter.py）。

令牌桶算法，支持：
  - 每分钟请求数 (RPM) 限制
  - 每天请求数 (RPD) 限制
  - 并发数限制 (Semaphore)
  - per-service 独立限流
  - 异步 acquire/release
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """速率限制配置。"""

    rpm: int = 0  # 每分钟请求数，0 = 无限制
    rpd: int = 0  # 每天请求数，0 = 无限制
    concurrency: int = 0  # 并发数，0 = 无限制
    burst: int = 1  # 令牌桶突发容量（默认 1）

    @classmethod
    def unlimited(cls) -> RateLimitConfig:
        return cls()


class TokenBucket:
    """令牌桶限流器。"""

    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: 令牌填充速率（个/秒）
            capacity: 桶容量
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._rate,
        )
        self._last_refill = now

    async def acquire(self, tokens: int = 1) -> None:
        """获取令牌，不足则等待。"""
        async with self._lock:
            self._refill()
            while self._tokens < tokens:
                wait_time = (tokens - self._tokens) / self._rate
                if wait_time <= 0:
                    break
                # 释放锁等待
                self._lock.release()
                try:
                    await asyncio.sleep(min(wait_time, 5.0))
                finally:
                    await self._lock.acquire()
                    self._refill()
            self._tokens -= tokens


class RateLimiter:
    """综合速率限制器（RPM + RPD + 并发）。"""

    def __init__(self, config: RateLimitConfig | None = None):
        self._config = config or RateLimitConfig.unlimited()

        # RPM 令牌桶
        self._rpm_bucket: TokenBucket | None = None
        if self._config.rpm > 0:
            # rate = rpm / 60 (tokens per second)
            self._rpm_bucket = TokenBucket(
                rate=self._config.rpm / 60.0,
                capacity=max(1, self._config.burst),
            )

        # RPD 计数器
        self._rpd_count = 0
        self._rpd_reset_time = time.time() + 86400
        self._rpd_lock = asyncio.Lock()

        # 并发信号量
        self._semaphore: asyncio.Semaphore | None = None
        if self._config.concurrency > 0:
            self._semaphore = asyncio.Semaphore(self._config.concurrency)

    @property
    def config(self) -> RateLimitConfig:
        return self._config

    async def acquire(self) -> None:
        """获取一次请求的许可（阻塞直到可用）。"""
        # RPM
        if self._rpm_bucket:
            await self._rpm_bucket.acquire()

        # RPD
        if self._config.rpd > 0:
            async with self._rpd_lock:
                now = time.time()
                if now >= self._rpd_reset_time:
                    self._rpd_count = 0
                    self._rpd_reset_time = now + 86400
                if self._rpd_count >= self._config.rpd:
                    wait_s = self._rpd_reset_time - now
                    logger.warning(
                        "RPD limit reached (%d/%d), waiting %.1fs",
                        self._rpd_count, self._config.rpd, wait_s,
                    )
                    self._rpd_lock.release()
                    try:
                        await asyncio.sleep(wait_s)
                    finally:
                        await self._rpd_lock.acquire()
                        self._rpd_count = 0
                        self._rpd_reset_time = time.time() + 86400
                self._rpd_count += 1

        # Concurrency
        if self._semaphore:
            await self._semaphore.acquire()

    def release(self) -> None:
        """释放并发许可（配合 acquire 使用）。"""
        if self._semaphore:
            self._semaphore.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()

    def stats(self) -> dict[str, Any]:
        """当前限流统计。"""
        result: dict[str, Any] = {
            "rpm_limit": self._config.rpm,
            "rpd_limit": self._config.rpd,
            "rpd_used": self._rpd_count,
            "concurrency_limit": self._config.concurrency,
        }
        if self._semaphore:
            result["concurrency_available"] = self._semaphore._value
        return result


# ── 全局限流器注册表 ──────────────────────────────────────────────────


class RateLimiterRegistry:
    """per-service 限流器注册表。

    用法：
        registry = RateLimiterRegistry()
        registry.register("openai", RateLimitConfig(rpm=500, rpd=2000))
        registry.register("minimax", RateLimitConfig(rpm=10, concurrency=3))

        async with registry.get("openai"):
            await call_openai_api()
    """

    def __init__(self):
        self._limiters: dict[str, RateLimiter] = {}

    def register(self, service: str, config: RateLimitConfig) -> RateLimiter:
        """注册或更新 service 的限流器。"""
        limiter = RateLimiter(config)
        self._limiters[service] = limiter
        logger.info(
            "registered rate limiter for %s: rpm=%d rpd=%d concurrency=%d",
            service, config.rpm, config.rpd, config.concurrency,
        )
        return limiter

    def get(self, service: str) -> RateLimiter | None:
        """获取 service 的限流器（未注册返回 None）。"""
        return self._limiters.get(service)

    def get_or_unlimited(self, service: str) -> RateLimiter:
        """获取限流器，未注册返回无限制限流器。"""
        return self._limiters.get(service, RateLimiter())

    def list_services(self) -> list[str]:
        return sorted(self._limiters.keys())

    def all_stats(self) -> dict[str, dict[str, Any]]:
        return {svc: lim.stats() for svc, lim in self._limiters.items()}


# ── 便捷工厂 ──────────────────────────────────────────────────────────


def create_limiter(
    *,
    rpm: int = 0,
    rpd: int = 0,
    concurrency: int = 0,
    burst: int = 1,
) -> RateLimiter:
    """快速创建限流器。"""
    return RateLimiter(RateLimitConfig(
        rpm=rpm, rpd=rpd, concurrency=concurrency, burst=burst,
    ))


# ── 全局注册表（模块级）──────────────────────────────────────────────

_GLOBAL_REGISTRY = RateLimiterRegistry()


def global_registry() -> RateLimiterRegistry:
    """获取全局限流器注册表。"""
    return _GLOBAL_REGISTRY


def register_global(service: str, **kwargs) -> RateLimiter:
    """注册全局限流器。"""
    return _GLOBAL_REGISTRY.register(service, RateLimitConfig(**kwargs))
