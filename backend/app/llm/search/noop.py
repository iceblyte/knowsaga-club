"""无检索 Provider —— MVP 的默认实现。

它不联网，但**也不是什么都不做**：它把「检索」这一步替换成「理解你的输入」，
并且明确把自己标记为 `degraded=True`。

为什么要有这个标记：`degraded` 不是「失败」，而是「本次出题没有外部资料做依据」。
调用方据此可以把进度文案说清楚（"已提炼 N 个核心概念" 而不是假装命中了资料），
也可以在日志里把「纯模型出题」的占比统计出来 —— 后续接真实 Provider 时，
这个比例就是判断要不要开联网的直接依据。
"""

from __future__ import annotations

from app.llm.search.base import SearchOutcome


class NoopSearchProvider:
    """不检索，仅作为出题链的占位与降级实现。"""

    name = "none"

    #: 不联网时，进度条第一步是「理解你的输入」而不是「联网检索知识」
    step_name = "理解你的输入"

    def search(self, query: str, *, limit: int = 6) -> SearchOutcome:  # noqa: ARG002
        """始终返回空结果并标记降级。

        Args:
            query: 用户输入。这里刻意不使用 —— 一旦「假装检索」去编造资料，
                就会变成最难发现的那类幻觉来源。
            limit: 无意义，仅为满足协议签名。
        """
        return SearchOutcome(provider=self.name, results=(), degraded=True)
