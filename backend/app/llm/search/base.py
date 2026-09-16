"""联网检索 Provider 抽象层。

## 为什么 MVP 只做抽象层，不做真实检索

已确认的决策：**MVP 纯模型出题**，联网检索只保留可切换的接口，开关在 `.env`。

但接口本身必须现在就有，而且必须**把「进度条第一步叫什么」也纳入接口**——
原型的「副本召唤中」屏第一步在联网时叫「联网检索知识」、不联网时叫「理解你的输入」。
如果前端自己判断该显示哪个，那么后续开启联网就得改前端。
所以约定：provider 决定步骤名与详情，前端只负责渲染（docs/MVP开发计划.md §7.3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SearchResult:
    """一条检索结果。"""

    title: str
    url: str
    snippet: str


@dataclass(frozen=True, slots=True)
class StepDescriptor:
    """进度条上一步的展示文案。前端直接渲染，不做判断。"""

    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """一次检索的结果。

    Attributes:
        provider: Provider 名，用于日志与排查。
        results: 命中的资料；降级时为空。
        degraded: 是否处于降级状态（未联网 / 检索失败但继续出题）。
    """

    provider: str
    results: tuple[SearchResult, ...] = ()
    degraded: bool = False

    @property
    def hit_count(self) -> int:
        return len(self.results)

    def first_step(self, *, concept_count: int) -> StepDescriptor:
        """第一步（`key=retrieve`）的最终文案。

        Args:
            concept_count: 从输入中提炼出的核心概念数。降级路径下用它构成提示，
                真实检索路径下改用命中条数。
        """
        if self.degraded:
            return StepDescriptor("理解你的输入", f"已提炼 {concept_count} 个核心概念")
        return StepDescriptor("联网检索知识", f"已完成 · 命中 {self.hit_count} 条资料")

    def as_reference(self, *, limit: int = 6) -> str:
        """拼成 Prompt 里的【参考资料】段落；无命中时返回空字符串。

        模型只被允许基于这里给出的资料作答，未开启检索时该段为空，
        Prompt 会明确要求「基于你已有的知识出题」。
        """
        if not self.results:
            return ""
        lines: list[str] = []
        for index, item in enumerate(self.results[:limit], 1):
            lines.append(f"[{index}] {item.title}\n{item.snippet}\n来源：{item.url}")
        return "\n\n".join(lines)


@runtime_checkable
class SearchProvider(Protocol):
    """检索 Provider 协议。

    实现方只需要三样东西：名字、进度条上第一步的名字、以及一个同步的 `search`。
    同步而非异步，是因为出题链整体跑在后台线程里，异步只会平白多一层调度。
    """

    name: str

    #: 该 Provider 在「副本召唤中」进度条上第一步的名字
    step_name: str

    def search(self, query: str, *, limit: int = 6) -> SearchOutcome:
        """检索资料。**不允许抛异常**：检索失败必须降级为空结果 + `degraded=True`，
        因为检索只是出题的增强项，不该把整个出题任务拖垮。"""
        ...
