"""检索 Provider 的选择入口。

当前已落地的实现只有 `noop`（`NoopSearchProvider`）—— 真实检索见下方 `_PROVIDERS` 的登记情况。
`bocha` 仍是「规划中但未接入」，命中它会报「尚未接入」而不是静默降级。

要接入一个新 Provider：按 `base.SearchProvider` 实现两个能力开关 + `initial_step()` + `gather()`，
再在下面的 `_PROVIDERS` 里登记即可；`get_search_provider` 会立刻开始返回它，
其余代码（进度文案、Prompt 参考资料段落）都不用改。
"""

from __future__ import annotations

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

logger = get_logger(__name__)

#: 已实现的 Provider 名 -> 构造器。P1 接入真实检索时在这里登记。
_PROVIDERS: dict[str, type] = {}

#: 规划中但尚未接入的名字。命中它们时报错要说清「是还没做」，而不是「配错了」。
_PLANNED: frozenset[str] = frozenset({"bocha", "tavily"})


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """按配置返回检索 Provider。

    规则：
    - `KNOWLEDGE_SEARCH_ENABLED=false` → 一律返回 `NoopSearchProvider`（MVP 默认路径）
    - 开关打开但 Provider 还没接入 → 抛 5000 并说明是未实现，避免静默降级成不联网
      （静默降级最糟：配置明明打开了，用户却以为在联网）
    """
    s = settings or get_settings()

    if not s.knowledge_search_enabled:
        return NoopSearchProvider()

    name = (s.knowledge_search_provider or "none").strip().lower()

    if name in ("", "none"):
        return NoopSearchProvider()

    if name in _PROVIDERS:
        return _PROVIDERS[name]()  # type: ignore[call-arg]

    if name in _PLANNED:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"联网检索 Provider「{name}」尚未接入，请先把 KNOWLEDGE_SEARCH_ENABLED 关掉",
            detail=f"provider={name} not implemented",
        )

    raise AppError(
        ErrorCode.INTERNAL_ERROR,
        f"未知的检索 Provider「{name}」，可选值：none",
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
    "get_search_provider",
]
