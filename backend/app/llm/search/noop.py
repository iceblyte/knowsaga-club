"""无检索 Provider —— 未开启联网检索时的默认实现。

## 它「不联网」指的是**不检索公开网络**

不带库时它什么都不做：把「取材」这一步替换成「理解你的输入」，
并把结果标记为没有资料（`degraded`，由「没有资料」派生）——
也不发任何外部请求（`tests/test_search_provider.py` 用「连 socket 都不许建立」钉住）。

**但带库时它必须真的去检索用户的资料**（design D8）。理由是配置的现实：
本机与大多数部署的默认组合就是 `KNOWLEDGE_SEARCH_ENABLED=false` +
自建知识库 —— 不改这一点的话，用户选了自己的库、上传解析好，出题时却一条资料都
拿不到，而日志上写着「取材未启用」，看起来完全正常。
所以带库的请求会走一轮循环，只是**没有任何联网工具可绑**。

## 为什么降级这个概念还在

`degraded` 不是「失败」，而是「本次出题没有资料做依据」。调用方据此把进度文案
说清楚（"已提炼 N 个核心概念"，而不是假装命中了资料），也可以在日志里统计
「纯模型出题」的占比 —— 后续判断要不要默认开联网，靠的就是这个比例。

⚠️ 它的 `can_search_web` / `can_read_pages` 都是 `False`，因此不带库时
`initial_step` **永远不会**给出「联网检索知识」或「读取你给的网页」——
没有能力就不许显示能力（见 `tests/test_search_provider.py` 的「冲突点 14」）。
知识库那一支相反：那条能力**跟着请求走**（带了库才有），所以它按 `request.has_kb` 算。
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.llm.search.base import (
    ReferenceCaps,
    SearchOutcome,
    SearchRequest,
    StepDescriptor,
    build_initial_step,
)

logger = get_logger(__name__)


class NoopSearchProvider:
    """不检索公开网络；带库时改为检索用户自己的资料。"""

    name = "none"

    #: 它不会主动联网检索
    can_search_web = False

    #: 它也不会按 URL 读整页 —— 用户贴的链接在这里读不到（这是真实的降级，会如实告知）
    can_read_pages = False

    def __init__(self, settings: Any | None = None, *, llm: Any | None = None) -> None:
        """构造。

        Args:
            settings: 配置。**只在带库的请求上会用到**（建知识库工具、取条数上限），
                不传时在 `gather()` 里取全局单例。既有的 `NoopSearchProvider()`
                无参调用行为不变（design D8）。
            llm: 注入模型（测试用），透传给 `run_search_agent`。
        """
        self._settings = settings
        self._llm = llm

    def initial_step(self, request: SearchRequest) -> StepDescriptor:
        """没有联网能力 ⇒ 恒为「理解你的输入」；**带了库**时是「检索你的知识库」。

        后者不算「显示没有的能力」：知识库检索依赖我们自己的向量库，
        与「配了哪个检索服务」无关，所以它是请求级的事实而不是 Provider 的能力位。
        """
        return build_initial_step(
            request,
            can_search_web=self.can_search_web,
            can_read_pages=self.can_read_pages,
            can_search_kb=request.has_kb,
        )

    def gather(self, request: SearchRequest, *, on_progress: object = None) -> SearchOutcome:
        """不带库时始终返回空结果；带库时走一轮循环（只绑 kb 工具）。

        Args:
            request: 带 `kb` 时才会真的做事（见类 docstring）。
            on_progress: 不带库时**刻意不使用** —— 一次外部调用都不发，没有过程可报；
                带库时透传给 `run_search_agent`。

        不带库时 `end_reason` 是 `disabled`（压根没打算联网）而不是某个失败原因：
        这条路径上没有任何外部调用发生过，把它说成「失败」会误导排查。
        """
        step = self.initial_step(request)

        if not request.has_kb:
            return SearchOutcome(
                provider=self.name, step_name=step.name, results=(), end_reason="disabled"
            )

        # 到这里的每一件 import 都是惰性的：知识库关掉的部署不该为它付出导入代价。
        from app.core.config import get_settings
        from app.llm.kb.tools import build_kb_tool
        from app.llm.search.agent import run_search_agent

        settings = self._settings or get_settings()
        return run_search_agent(
            request,
            settings=settings,
            provider_name=self.name,
            llm=self._llm,
            # `(None, None)`：它确实一个联网工具都没有。用 `tools=None` 会去
            # `build_tavily_tools()` 要 key —— 那等于把「没开联网」变成一次配置错误。
            tools=(None, None),
            kb_tool=build_kb_tool(request, settings),
            caps=ReferenceCaps.from_settings(settings),
            on_progress=on_progress,  # type: ignore[arg-type]
        )
