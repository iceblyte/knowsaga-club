"""进程内滑动窗口限流。

## 为什么用进程内内存而不引 Redis

方案 §2.1 明确「不引入 Redis」。限流要保护的是**登录接口**
（`code` 换来换去就能无限建档），触发场景是脚本刷接口 ——
单进程内存计数已足够拦住它。代价是「多实例部署时各算各的」，
那时再换成集中式计数器即可（只改这一个模块）。

## 为什么按 IP 而不按 openid

在登录接口上，识别用户身份恰恰是**还没完成**的那一步。
IP 是此时唯一可得、且与「同一台脚本机器」强相关的维度。

## 为什么用单调时钟

`time.monotonic()` 不受系统时间调整影响。用 `time.time()` 的话，
改一次系统时间就能把窗口「拨回去」从而绕过限流。
"""

from __future__ import annotations

import time
from collections import deque

from app.core.config import get_settings
from app.core.exceptions import rate_limited

#: 键数量超过它时做一次全量清理，防止大量不同 IP 把内存撑大
_PRUNE_THRESHOLD = 512


class SlidingWindowLimiter:
    """滑动窗口计数器：窗口内最多允许 `limit` 次。

    为什么是滑动窗口而不是固定窗口：固定窗口在边界处能放过 2 倍流量
    （窗口末尾冲一次、下个窗口开头再冲一次），对一个「保护建档能力」
    的需求来说，这个漏口不值得留。
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = max(1, int(limit))
        self._window = max(1, int(window_seconds))
        self._hits: dict[str, deque[float]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def window_seconds(self) -> int:
        return self._window

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """记一次并返回是否放行（不修改任何状态当返回 False）。"""
        moment = time.monotonic() if now is None else now
        cutoff = moment - self._window

        bucket = self._hits.setdefault(key, deque())
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self._limit:
            return False

        bucket.append(moment)
        if len(self._hits) > _PRUNE_THRESHOLD:
            self._prune(cutoff)
        return True

    def retry_after_seconds(self, key: str, *, now: float | None = None) -> int:
        """还要等多少秒才有下一次额度（用于 `Retry-After` 语义）。"""
        bucket = self._hits.get(key)
        if not bucket:
            return 0
        moment = time.monotonic() if now is None else now
        return max(1, int(bucket[0] + self._window - moment) + 1)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)

    def _prune(self, cutoff: float) -> None:
        stale = [k for k, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._hits.pop(key, None)


#: 已注册的限流器（供测试逐用例清零）
_REGISTRY: dict[str, SlidingWindowLimiter] = {}

#: 已生效的配置指纹，用于在配置变化时重建限流器
_CONFIG_SEEN: dict[str, tuple[int, int]] = {}


def _limiter(name: str, limit: int, window_seconds: int) -> SlidingWindowLimiter:
    """取（必要时重建）具名限流器。

    为什么要看配置重建：测试里会通过环境变量把阈值调小，
    若限流器在 import 时就把阈值固化，改配置将毫无效果 ——
    那正是「测试看起来通过了但什么都没验证」的典型来源。
    """
    fingerprint = (int(limit), int(window_seconds))
    existing = _REGISTRY.get(name)
    if existing is not None and _CONFIG_SEEN.get(name) == fingerprint:
        return existing

    limiter = SlidingWindowLimiter(limit, window_seconds)
    _REGISTRY[name] = limiter
    _CONFIG_SEEN[name] = fingerprint
    return limiter


def enforce(name: str, key: str) -> None:
    """按当前配置限流；超限即抛 4290。

    Args:
        name: 限流通道名（各通道独立计数）。
        key: 计数维度，登录接口用来源 IP。
    """
    settings = get_settings()
    limiter = _limiter(name, settings.login_rate_limit, settings.login_rate_window_seconds)
    if not limiter.allow(key):
        raise rate_limited(
            detail=f"channel={name} key={key} 超出 {limiter.limit} 次/{limiter.window_seconds}s"
        )


def reset_all() -> None:
    """清空全部计数与配置指纹（测试用）。"""
    for limiter in _REGISTRY.values():
        limiter.reset()
    _REGISTRY.clear()
    _CONFIG_SEEN.clear()
