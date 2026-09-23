"""无检索 Provider —— 未开启联网检索时的默认实现。

它不联网，但**也不是什么都不做**：它把「取材」这一步替换成「理解你的输入」，
并把自己的结果标记为降级（`degraded`，由「没有资料」派生）。

为什么要有降级这个概念：`degraded` 不是「失败」，而是「本次出题没有外部资料做依据」。
调用方据此把进度文案说清楚（"已提炼 N 个核心概念"，而不是假装命中了资料），
也可以在日志里统计「纯模型出题」的占比 —— 后续判断要不要默认开联网，靠的就是这个比例。

⚠️ 它的 `can_search_web` / `can_read_pages` 都是 `False`，因此 `initial_step`
**永远不会**给出「联网检索知识」或「读取你给的网页」——
没有能力就不许显示能力（见 `tests/test_search_provider.py` 的文件头「冲突点 14」）。
"""

from __future__ import annotations

from app.llm.search.base import (
    SearchOutcome,
    SearchRequest,
    StepDescriptor,
    build_initial_step,
)


class NoopSearchProvider:
    """不检索，仅作为出题链的占位与降级实现。"""

    name = "none"

    #: 它不会主动联网检索
    can_search_web = False

    #: 它也不会按 URL 读整页 —— 用户贴的链接在这里读不到（这是真实的降级，会如实告知）
    can_read_pages = False

    def initial_step(self, request: SearchRequest) -> StepDescriptor:
        """没有能力 ⇒ 恒为「理解你的输入」。"""
        return build_initial_step(
            request, can_search_web=self.can_search_web, can_read_pages=self.can_read_pages
        )

    def gather(self, request: SearchRequest, *, on_progress: object = None) -> SearchOutcome:  # noqa: ARG002
        """始终返回空结果。

        Args:
            request: 刻意不使用 —— 一旦「假装检索」去编造资料，
                就会变成最难发现的那类幻觉来源。
            on_progress: 刻意不使用 —— 它一次外部调用都不发，没有过程可报。

        `end_reason` 是 `disabled`（压根没打算联网）而不是某个失败原因：
        这条路径上没有任何外部调用发生过，把它说成「失败」会误导排查。
        """
        return SearchOutcome(
            provider=self.name,
            step_name=self.initial_step(request).name,
            results=(),
            end_reason="disabled",
        )
