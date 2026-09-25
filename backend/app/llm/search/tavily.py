"""基于官方 `langchain-tavily` 两个工具的真实检索 Provider。

它把「取材请求」转交给 `agent.run_search_agent`，自己只做两件事：
**开工前校验配置**（key 缺失要立刻报错，而不是建了任务再失败）与
**把两个能力开关声明为真**（决定第一步有没有资格叫「联网检索知识」/「读取你给的网页」）。

## 为什么在 `__init__` 就校验 key

`get_search_provider()` 在 `submit_quiz_request` 里、`create_task` **之前**被调用。
在这里抛错 = 用户直接看到「配置错了」，而不是拿到一个任务 id、
等几秒后看到一个已经失败的任务（design D13）。
"""

from __future__ import annotations

from typing import Any, Callable

from app.core.config import Settings
from app.llm.search.agent import ProgressCallback, describe_step, run_search_agent
from app.llm.search.base import ReferenceCaps, SearchOutcome, SearchRequest, StepDescriptor
from app.llm.search.tavily_tools import require_tavily_key

class TavilySearchProvider:
    """关键词检索 + 按 URL 读整页，都由模型自己决定何时调用。"""

    name = "tavily"

    #: 它能主动联网检索
    can_search_web = True

    #: 它也能按 URL 读整页
    can_read_pages = True

    def __init__(
        self,
        settings: Settings,
        *,
        on_progress: ProgressCallback | None = None,
        llm: Any | None = None,
        tools: tuple[Any, Any] | None = None,
        caps: ReferenceCaps | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """构造时校验配置，并保留注入点（测试用）。

        Raises:
            AppError(5000): 未配置 `TAVILY_API_KEY`。
        """
        require_tavily_key(settings)
        self._settings = settings
        self._on_progress = on_progress
        self._llm = llm
        self._tools = tools
        self._caps = caps
        self._clock = clock

    def initial_step(self, request: SearchRequest) -> StepDescriptor:
        """三态：有链接 → 「读取你给的网页」；想搜 → 「联网检索知识」；都不是 → 「理解你的输入」。"""
        # 传 settings 是因为「有没有知识库那一支」还取决于功能开关（design D7）。
        return describe_step(request, self._settings)

    def gather(self, request: SearchRequest, *, on_progress: ProgressCallback | None = None) -> SearchOutcome:
        """跑一轮有界取材。

        **不允许抛异常**（取不到就降级）。唯一的例外是配置错误 ——
        而它在 `__init__` 就已经拦下了，走到这里说明配置是好的。

        Args:
            on_progress: 本次调用的进度回调；不传则用构造时给的那个。
        """
        # 惰性 import：`app.llm.kb.tools` 会拉起知识库那一层，而联网检索在
        # 知识库关掉时必须能独立工作（`llm/kb/__init__.py` 的头注释是同一条理由）。
        # 它自身不 import chromadb，所以这里不存在「打开开关才付代价」的破例。
        from app.llm.kb.tools import build_kb_tool

        return run_search_agent(
            request,
            settings=self._settings,
            provider_name=self.name,
            llm=self._llm,
            tools=self._tools,
            kb_tool=build_kb_tool(request, self._settings),
            caps=self._caps,
            on_progress=on_progress or self._on_progress,
            clock=self._clock,
        )


__all__ = ["TavilySearchProvider"]
