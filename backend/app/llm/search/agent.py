"""模型自主取材的**有界循环**（design D5）。

## 形状

    假模型 / DeepSeek bind_tools([tavily_search, tavily_extract])
        ↓ for round in range(max_rounds)
        ToolMessage 回喂 → 模型决定下一轮
        ↓
    收集好的资料 → collector.collect_results() → SearchOutcome

## 三个必须由我们自己守住的东西

1. **有界**：`create_agent` 只有 `recursion_limit` 一个间接旋钮（且它数的是图步数不是工具
   调用数），而 `search_agent_max_rounds` / `search_agent_max_tool_calls` /
   `search_agent_budget_seconds` 必须**精确可控**。每个上限触顶都留一条含上限名的
   warning —— 「这次为什么只搜到 1 条」要能直接从日志看出来。
2. **超时**：上游 `_utilities.py` 的 `requests.post(...)` **没有 `timeout`**（0.2.18 已核源码），
   网络黑洞下会无限等。外包一层**模块级有界线程池**是我们自己的代码，与上游版本解耦。
   ⚠️ 残余风险：超时后那个线程不会被回收，`requests` 仍可能挂着；连续卡死会让 4 个 worker
   占满 → 后续调用立刻超时 → 降级出题。这是**可预测的降级**，不是无界增长（design D12）。
   另：extract 与 search **不共用**上限（`_timeout_for`）—— 整页正文实测 2.2 万–7.5 万字符，
   用 search 的 8s 上限会让「用户贴的链接读不到」。
3. **用户给的链接必读**：即使模型一轮都不调工具，循环启动时也先由服务端直接 extract 一次
   那批 URL。理由：用户会拿题目跟浏览器里的原文逐字对照，「我贴了链接却没被读」
   是这个产品最不能出现的失败（design D4）。

## 为什么不用 `tool_choice` 强制

`tool_choice` 与 DeepSeek 的思考模式有冲突历史（本项目已因此显式关掉思考模式），
而这里要的本来就是「让模型自己决定调不调、调哪个」——`auto` 正是想要的语义。
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from langchain_core.messages import BaseMessage, ToolMessage

from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.search.base import (
    KB_TOOL_NAME,
    EndReason,
    ReferenceCaps,
    SearchOutcome,
    SearchRequest,
    StepDescriptor,
    build_initial_step,
    truncate,
)
from app.llm.search.collector import ToolOutput, collect_results
from app.llm.search.tavily_tools import build_tavily_tools
from app.prompts.search_prompt import build_agent_messages

logger = get_logger(__name__)

#: 执行工具调用的线程池上界。**必须有界**：超时的线程不会被回收（见模块 docstring 第 2 条）。
TOOL_POOL_MAX_WORKERS = 4

#: 回喂给模型的工具结果上限。
#: ⚠️ 这与「注入出题 Prompt 的资料上限」**不是同一件事**：那个由 `ReferenceCaps` 管，
#: 决定模型能依据多少资料；这个只管「循环能不能继续问下去」。
#: 不截断的话，一次 extract（实测单页 7.5 万字符）就能把对话上下文撑爆。
TOOL_MESSAGE_MAX_CHARS = 8000

_pool: ThreadPoolExecutor | None = None


def get_tool_pool() -> ThreadPoolExecutor:
    """模块级线程池（懒建）。整个进程共用一个，避免每次取材新建池。"""
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=TOOL_POOL_MAX_WORKERS, thread_name_prefix="search-tool")
    return _pool


@dataclass(frozen=True, slots=True)
class ToolProgress:
    """一次工具调用的进度。前端把它变成「进度条第一步现在在干什么」。

    Attributes:
        tool: 工具名。
        phase: `start`（已发出）/ `done`（成功返回）/ `failed`（超时或异常）。
        count: 本次调用涉及的条目数 —— search 是 1 组关键词，extract 是网页数。
        detail: 给用户看的一句话。**含动作与数量**。
    """

    tool: str
    phase: Literal["start", "done", "failed"]
    count: int
    detail: str


ProgressCallback = Callable[[ToolProgress], None]


def _emit(callback: ProgressCallback | None, progress: ToolProgress) -> None:
    """回调是**装饰性**的：它抛异常不该中断取材。"""
    if callback is None:
        return
    try:
        callback(progress)
    except Exception:  # noqa: BLE001 - 进度回调不该影响主流程
        logger.debug("取材进度回调抛异常，已忽略", exc_info=True)


def _timeout_for(tool_name: str, settings: Settings) -> float:
    """按工具取超时上限。**extract 必须比 search 宽松**（design D12 / §12.4）。

    一次 `tavily_extract` 取回的是**整页正文**（实测单页 2.2 万–7.5 万字符），
    而 search 只回一小段 JSON。两者共用同一个上限的后果是「用户贴的链接读不到」——
    而那正是本产品最不能失败的一条路径（design D4）。

    `kb_search` 与 `tavily_search` **同一档**（落到下面的默认分支）：它的回传体积
    同量级（最多 `kb_search_top_k` 段，每段又要过 `snippet_max_chars`），
    慢的那部分只是内部**一次**向量化调用，不是「一页 7 万字符」。
    给它 extract 那一档会平白吃掉总预算 —— 而预算被吃掉的表现是
    「后面那几次调用全部超时」，看起来像是检索服务坏了。

    ⚠️ 这个分支**不能**写成「默认值 + 特殊情况」那种顺序，否则以后新增工具时
    容易漏掉；这里显式按名字判定，未知工具回落到 `search_tool_timeout_seconds`。
    """
    if tool_name == "tavily_extract":
        return settings.search_extract_timeout_seconds
    return settings.search_tool_timeout_seconds


def _invoke_tool(tool: Any, args: dict, *, timeout: float) -> ToolOutput:
    """在**有界线程池**里执行一次工具调用，并在外部套一层超时（design D12）。

    Returns:
        `ToolOutput`。任何异常（含超时、`ToolException`）都被转成 `ok=False`，
        **绝不向上抛** —— `gather` 的契约是不允许抛异常。
    """
    name = getattr(tool, "name", "unknown")
    try:
        future = get_tool_pool().submit(tool.invoke, args)
    except Exception as exc:  # noqa: BLE001 - 池已关闭等极端情况
        logger.warning("取材工具无法提交到线程池：tool=%s error=%s", name, exc)
        return ToolOutput(tool=name, ok=False, error=f"{type(exc).__name__}: {exc}")

    try:
        payload = future.result(timeout=timeout)
    except FuturesTimeout:
        logger.warning(
            "取材调用超时（>%ss），已放弃该次：tool=%s（上游 requests.post 无 timeout，见 design D12）",
            timeout,
            name,
        )
        return ToolOutput(tool=name, ok=False, error=f"调用超时（>{timeout}s）")
    except Exception as exc:  # noqa: BLE001 - 上游把错误藏在 ToolException / 各种异常里
        logger.warning("取材调用失败：tool=%s error=%s", name, exc)
        return ToolOutput(tool=name, ok=False, error=f"{type(exc).__name__}: {exc}")

    return ToolOutput(tool=name, payload=payload, ok=True)


def _render_for_model(output: ToolOutput) -> str:
    """把工具产出转成给模型看的文本，**必须有界**（见 `TOOL_MESSAGE_MAX_CHARS`）。

    采集用的是 `output.payload` 原样，不经过这里 —— 截断只影响模型这一侧。
    """
    if not output.ok:
        return f"调用失败：{output.error}"
    payload = output.payload
    if isinstance(payload, str):
        return truncate(payload, TOOL_MESSAGE_MAX_CHARS)
    if isinstance(payload, dict):
        try:
            return truncate(json.dumps(payload, ensure_ascii=False, default=str), TOOL_MESSAGE_MAX_CHARS)
        except Exception:  # noqa: BLE001 - 不可序列化的返回不该中断循环
            return truncate(str(payload), TOOL_MESSAGE_MAX_CHARS)
    return truncate(str(payload), TOOL_MESSAGE_MAX_CHARS)


def _call_count(tool_name: str, args: dict) -> int:
    """本次调用涉及的条目数：search 与 kb 都是 1 组关键词，extract 是网页数。"""
    if tool_name == "tavily_extract":
        urls = args.get("urls")
        return len(urls) if isinstance(urls, list) and urls else 1
    return 1


def _describe(tool_name: str, phase: str, count: int, args: dict) -> str:
    """进度文案。**必须含数量** —— 用户在等待时最想知道的是「在读几个页面」。

    知识库那一支（`kb_search`）单独写一份，而不是复用 search 的文案：
    用户选了「只用自己的资料」时，进度上说「正在检索 1 组关键词」会让人以为
    这次同时还在网上搜。**说清范围**是这里唯一要额外做的事，其余沿用同样的
    「动作 + 数量 + 检索词」结构（用户才知道我们在查什么）。
    """
    if tool_name == "tavily_extract":
        return {
            "start": f"正在读取 {count} 个网页",
            "done": f"读取完成 {count} 个网页",
            "failed": f"读取失败（{count} 个网页）",
        }[phase]
    query = str(args.get("query") or "").strip()
    short = query[:30] + ("…" if len(query) > 30 else "")
    if tool_name == KB_TOOL_NAME:
        return {
            "start": f"正在检索你的资料（{count} 组关键词）：{short}",
            "done": f"你的资料检索完成（{count} 组关键词）",
            "failed": f"你的资料检索失败（{count} 组关键词）",
        }[phase]
    return {
        "start": f"正在检索 {count} 组关键词：{short}",
        "done": f"检索完成 {count} 组关键词",
        "failed": f"检索失败（{count} 组关键词）",
    }[phase]


def run_search_agent(
    request: SearchRequest,
    *,
    settings: Settings,
    provider_name: str = "tavily",
    llm: Any | None = None,
    tools: tuple[Any, Any] | None = None,
    kb_tool: Any | None = None,
    caps: ReferenceCaps | None = None,
    on_progress: ProgressCallback | None = None,
    clock: Callable[[], float] | None = None,
) -> SearchOutcome:
    """跑一轮取材。**这个函数不抛异常** —— 取不到资料就降级为空结果。

    Args:
        request: 本次取材请求。
        settings: 配置（三个上限、超时、条数、key）。
        provider_name: 写进 `SearchOutcome.provider`，仅用于日志与排查。
        llm: 注入模型（测试用）；不传则用 `build_chat_model("quiz")`。
        tools: 注入 `(search_tool, extract_tool)`（测试用）；不传则按配置构造。
            ⚠️ 元素可以是 `None` —— 「这个 Provider 没有那个工具」是合法状态
            （`NoopSearchProvider` 就是 `(None, None)`），而不是「没注入」。
        kb_tool: 注入 `kb_search` 工具（`llm/kb/tools.build_kb_tool`）。
            **只有 `request.has_kb` 时才绑**；不传则本次不会检索用户资料（记 warning）。
        caps: 单条截断上限；不传则从 `settings` 取。
        on_progress: 每次工具调用前后回调。
        clock: 时钟（测试注入假时钟用）；默认 `time.monotonic`。
    """
    now = clock or time.monotonic
    caps = caps or ReferenceCaps.from_settings(settings)

    # 既不想碰外部网络、也没带库：一次模型调用都不该发生
    # （provider 层通常会先拦，这里是兜底）
    if not request.wants_grounding:
        step = build_initial_step(request, can_search_web=False, can_read_pages=False)
        return SearchOutcome(provider=provider_name, step_name=step.name, end_reason="disabled")

    deadline = now() + settings.search_agent_budget_seconds

    if tools is None:
        # 未配 key 会在这里抛 —— 那是**配置错误**（5000），按 design D13 允许上抛
        search_tool, extract_tool = build_tavily_tools(request, settings)
    else:
        search_tool, extract_tool = tools

    if request.has_kb and kb_tool is None:
        # 「用户选了自己的库、界面上看着也选上了，但这次一条资料都没查」——
        # 这条链路整段静默（没有异常、没有失败状态），所以必须留一条日志。
        logger.warning(
            "请求带了知识库，但调用方没有提供 kb 工具，本次不会检索用户资料：kb_id=%s",
            getattr(request.kb, "kb_id", None),
        )

    # 第一步的名字必须与**真的绑了什么工具**一致（红线：文案不许说没有的能力）：
    # `NoopSearchProvider` 的 `tools=(None, None)` 若被当成「能联网」，
    # 用户会看到「联网检索知识」而它一次网络都不会碰。
    step = build_initial_step(
        request,
        can_search_web=search_tool is not None,
        can_read_pages=extract_tool is not None,
        can_search_kb=request.has_kb and kb_tool is not None,
    )

    if llm is None:
        from app.llm.langchain_factory import build_chat_model

        llm = build_chat_model("quiz", settings=settings)

    # 关掉搜索时连工具都不给 —— 让「不该发生」变成「不可能发生」。
    # 这不只是防御：模型看到工具就会想用，绑定再拒绝调用等于跟它较劲。
    #
    # ⚠️ 知识库工具**不看 `use_search`**：kb 不是联网。用户关掉「公开检索」
    # 之后仍然要能「只用我自己的资料出题」，否则那个诉求根本没法表达（design D7）。
    # 但它**必须看 `request.has_kb`**：这次没选库却把工具绑给模型，
    # 模型就会去调（描述里明明写着「用户自己的资料库」），
    # 而这次要用的资料并不在默认库里 —— 用户会拿到一份与自己的材料无关的题。
    candidates: list[Any | None] = [] if not request.use_search else [search_tool]
    candidates.append(extract_tool)
    candidates.append(kb_tool if request.has_kb else None)
    offered = [tool for tool in candidates if tool is not None]

    if not offered:
        # 「想去取资料」但手里一个工具都没有（`NoopSearchProvider` + 用户贴了链接
        # 就一定会走到这里）。如实说 `disabled`，而不是硬跑一圈：
        # `bind_tools([])` 的行为取决于具体模型实现，而后面那圈链接兜底
        # 会对着 `None.invoke()` 抛 `AttributeError`。
        logger.info("取材请求没有任何可用工具，直接收尾：provider=%s", provider_name)
        return SearchOutcome(provider=provider_name, step_name=step.name, end_reason="disabled")

    bound = llm.bind_tools(offered)

    outputs: list[ToolOutput] = []
    tool_calls_used = 0
    rounds_used = 0
    end_reason: EndReason = "done"

    # ----------------------------------------------------------- 链接兜底
    # 服务端先读一次用户给的链接（design D4）。它**不计入** tool_calls_used ——
    # 那个上限管的是模型的调用次数，不是我们自己的兜底。
    #
    # ⚠️ 没有 extract 工具时**必须跳过**：`NoopSearchProvider` 的
    # `can_read_pages=False`，它根本没有那个工具，不跳过就是一次
    # `AttributeError: 'NoneType' object has no attribute 'invoke'`。
    # 这次读不到链接是**真实的降级**，如实体现在结果里（`degraded`），不假装读过。
    if request.urls and extract_tool is not None:
        args = {"urls": list(request.urls)}
        count = len(request.urls)
        _emit(on_progress, ToolProgress("tavily_extract", "start", count, f"正在读取 {count} 个链接"))
        output = _invoke_tool(extract_tool, args, timeout=_timeout_for("tavily_extract", settings))
        outputs.append(output)
        _emit(
            on_progress,
            ToolProgress(
                "tavily_extract",
                "done" if output.ok else "failed",
                count,
                f"已读取 {count} 个链接" if output.ok else f"读取链接失败（{count} 个）",
            ),
        )
    elif request.urls:
        logger.warning(
            "本次没有读取用户给的链接（该 Provider 没有按 URL 读整页的能力）：count=%s",
            len(request.urls),
        )

    # ----------------------------------------------------------- 有界循环
    messages: list[BaseMessage] = build_agent_messages(request, max_rounds=settings.search_agent_max_rounds)

    while True:
        if rounds_used >= settings.search_agent_max_rounds:
            end_reason = "rounds_exhausted"
            logger.warning(
                "取材触到轮次上限，停止循环：%s=%s", "rounds_exhausted", settings.search_agent_max_rounds
            )
            break
        if now() > deadline:
            end_reason = "budget_exhausted"
            logger.warning("取材触到总时长上限，停止循环：budget_exhausted=%s", settings.search_agent_budget_seconds)
            break

        rounds_used += 1
        try:
            ai = bound.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - 模型侧失败不能拖垮出题
            logger.warning("取材循环里模型调用失败，已降级收尾：%s", exc)
            end_reason = "error"
            break

        messages.append(ai)
        calls = list(getattr(ai, "tool_calls", None) or [])
        if not calls:
            # 第一轮就不要工具 = 模型认为不需要外部资料；后续轮次不要工具 = 正常收尾
            end_reason = "no_tool_calls" if rounds_used == 1 else "done"
            break

        stop = False
        for call in calls:
            if tool_calls_used >= settings.search_agent_max_tool_calls:
                end_reason = "tool_calls_exhausted"
                logger.warning(
                    "取材触到工具调用次数上限，停止循环：tool_calls_exhausted=%s",
                    settings.search_agent_max_tool_calls,
                )
                stop = True
                break
            if now() > deadline:
                end_reason = "budget_exhausted"
                logger.warning(
                    "取材触到总时长上限，停止循环：budget_exhausted=%s", settings.search_agent_budget_seconds
                )
                stop = True
                break

            tool_calls_used += 1
            name = str(call.get("name") or "")
            args = call.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            count = _call_count(name, args)
            tool = next((t for t in offered if getattr(t, "name", None) == name), None)

            if tool is None:
                # 模型点名了一个没绑给它的工具（例如关掉搜索后仍要 search）。
                # 记一条 ToolMessage 把话说明白，让它在下一轮改主意，而不是原地重试。
                logger.warning("模型请求了未绑定的工具，已拒绝：name=%s", name)
                messages.append(
                    ToolMessage(content=f"工具 {name or '(空名)'} 不可用，请改用其它方式或直接结束。", tool_call_id=str(call.get("id") or ""))
                )
                continue

            _emit(on_progress, ToolProgress(name, "start", count, _describe(name, "start", count, args)))
            output = _invoke_tool(tool, args, timeout=_timeout_for(name, settings))
            outputs.append(output)
            phase = "done" if output.ok else "failed"
            _emit(on_progress, ToolProgress(name, phase, count, _describe(name, phase, count, args)))
            messages.append(
                ToolMessage(content=_render_for_model(output), tool_call_id=str(call.get("id") or ""), name=name)
            )

        if stop:
            break

    results = collect_results(outputs, request=request, caps=caps)
    outcome = SearchOutcome(
        provider=provider_name,
        step_name=step.name,
        results=results,
        rounds_used=rounds_used,
        tool_calls_used=tool_calls_used,
        end_reason=end_reason,
    )
    logger.info(
        "取材结束：provider=%s reason=%s rounds=%s calls=%s hits=%s",
        provider_name,
        end_reason,
        rounds_used,
        tool_calls_used,
        outcome.hit_count,
    )
    return outcome


def describe_step(request: SearchRequest, settings: Settings) -> StepDescriptor:
    """给外部（Provider）复用的第一步文案，避免两处各推一遍 `can_*`。

    ⚠️ 这里假定调用方**有联网能力**（它是给 `TavilySearchProvider` 用的）。
    知识库那一支反过来——**不能**写成 Provider 的静态能力位：同一个 Tavily
    Provider，带库的请求该能检索知识库、不带库的不该，所以按请求算（design D7）。
    这与 `run_search_agent` 里那份判定必须给出同一个名字，否则
    「进度卡上的名字」与「几秒后回来的 `step_name`」会对不上。

    ⚠️ 知识库那一支还看**功能开关**：`build_kb_tool()` 在开关关掉时返回 `None`，
    实际不会绑工具。这里必须跟着一起为假 —— 否则进度卡会预告
    「检索你的知识库」而全程一次都不查（红线：文案不许说没有的能力）。
    """
    return build_initial_step(
        request,
        can_search_web=True,
        can_read_pages=True,
        can_search_kb=request.has_kb and settings.knowledge_base_enabled,
    )


__all__ = [
    "TOOL_MESSAGE_MAX_CHARS",
    "TOOL_POOL_MAX_WORKERS",
    "ToolProgress",
    "describe_step",
    "get_tool_pool",
    "run_search_agent",
]
