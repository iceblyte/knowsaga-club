"""检索 Provider 的选择入口。

已落地的实现有两个：`noop`（默认，不联网）与 `tavily`（真实检索 + 按 URL 读整页）。
`bocha` 仍是「规划中但未接入」，命中它会报「尚未接入」而不是静默降级 ——
「还没做」与「配错了」是两句不同的话，别合流。

要接入一个新 Provider：按 `base.SearchProvider` 实现 `name` / 两个能力开关 /
`initial_step()` / `gather()`，再在下面的 `_PROVIDERS` 里登记即可；
其余代码（进度文案、Prompt 参考资料段落、资料快照落库）都不用改。
"""

from __future__ import annotations

from typing import Callable

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, ErrorCode
from app.core.logging import get_logger
from app.llm.search.base import (
    ReferenceCaps,
    SearchOutcome,
    SearchProvider,
    SearchRequest,
    SearchResult,
    StepDescriptor,
)
from app.llm.search.noop import NoopSearchProvider
from app.llm.search.tavily import TavilySearchProvider

logger = get_logger(__name__)

#: Provider 构造器签名 —— 都接受 `(settings, *, on_progress=...)`。
ProviderFactory = Callable[..., SearchProvider]

#: 已实现的 Provider 名 -> 构造器。
_PROVIDERS: dict[str, ProviderFactory] = {
    "tavily": TavilySearchProvider,
}

#: 规划中但尚未接入的名字。命中它们时报错要说清「是还没做」，而不是「配错了」。
_PLANNED: frozenset[str] = frozenset({"bocha"})

#: 「未知名字」文案里列出的可选值。**不要用 `list(_PROVIDERS)` 现算** ——
#: 那句话是给配错的人看的，`none` 也得在里面，否则他按提示改完还是错。
_KNOWN_NAMES = ("none", *_PROVIDERS)


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """按配置返回检索 Provider。

    规则：
    - `KNOWLEDGE_SEARCH_ENABLED=false` → 一律返回 `NoopSearchProvider`
    - 开关打开但 Provider 还没接入 → 抛 5000 并说明是未实现，避免静默降级成不联网
      （静默降级最糟：配置明明打开了，用户却以为在联网）
    - 开关打开、名字对、但 key 为空 → 同样是 5000，且**在 `create_task` 之前**抛出，
      用户直接看到「配置错了」而不是一个注定失败的任务（design D13）

    Args:
        settings: 注入配置（测试用）；默认取全局单例。
    """
    s = settings or get_settings()

    if not s.knowledge_search_enabled:
        return NoopSearchProvider()

    name = (s.knowledge_search_provider or "none").strip().lower()

    if name in ("", "none"):
        return NoopSearchProvider()

    factory = _PROVIDERS.get(name)
    if factory is not None:
        return factory(s)

    if name in _PLANNED:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"联网检索 Provider「{name}」尚未接入，请先改回 tavily 或把 KNOWLEDGE_SEARCH_ENABLED 关掉",
            detail=f"provider={name} not implemented",
        )

    raise AppError(
        ErrorCode.INTERNAL_ERROR,
        f"未知的检索 Provider「{name}」，可选值：{'、'.join(_KNOWN_NAMES)}",
        detail=f"provider={name} unknown",
    )


__all__ = [
    "NoopSearchProvider",
    "ReferenceCaps",
    "SearchOutcome",
    "SearchProvider",
    "SearchRequest",
    "SearchResult",
    "StepDescriptor",
    "TavilySearchProvider",
    "get_search_provider",
]
