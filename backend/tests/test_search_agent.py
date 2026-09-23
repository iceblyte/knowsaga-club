"""模型自主取材的**有界循环**（`add-web-search-grounding` 第 4 组）。

## 为什么不测真实模型

与项目「pytest 里 LLM 一律 mock」一致：这里注入一个**按脚本返回 `tool_calls` 的假模型**
与**假工具**，一个包都不联网。真实链路只在第 0 组的探查脚本与第 11 组的端到端里跑。

## 这一组要守住的三件事

1. **有界**：轮次、工具调用次数、总时长三个上限都必须真的拦得住，且各留一条含上限名的
   日志 —— 「这次为什么只搜到 1 条」要能在日志里直接看出来（design D5）。
2. **超时**：上游 `requests.post` **没有 timeout**（第 0 组复核），网络黑洞下会无限等。
   外包一层有界线程池是我们自己的代码，升级上游不会失效（design D12）。
3. **用户给的链接必读**：即使模型一轮都不调工具，服务端也要兜底读一次 ——
   「我贴了链接却没被读」是本产品最不能出现的失败（design D4）。
"""

from __future__ import annotations

import logging
import time

import pytest
from langchain_core.messages import AIMessage

from app.core.config import Settings
from app.llm.search import agent as agent_module
from app.llm.search.agent import ToolProgress, run_search_agent
from app.llm.search.base import ReferenceCaps, SearchRequest

USER_URL = "https://user.example/page"
OTHER_URL = "https://other.example/post"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "knowledge_search_enabled": True,
        "knowledge_search_provider": "tavily",
        "tavily_api_key": "test-key",
        "search_agent_max_rounds": 3,
        "search_agent_max_tool_calls": 4,
        "search_agent_budget_seconds": 20,
        "search_tool_timeout_seconds": 1,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


CAPS = ReferenceCaps(snippet_max_chars=200, page_max_chars=300, total_max_chars=2000)


# ---------------------------------------------------------------- 假工具 / 假模型
class FakeTool:
    """假工具：记录调用参数，按构造时给的行为返回。

    `returns` 传可调用对象时按调用参数现算返回值，用来模拟「不同 query 不同结果」。
    """

    def __init__(self, name: str, returns: object = None, *, delay: float = 0.0, raises: Exception | None = None):
        self.name = name
        self._returns = returns
        self._delay = delay
        self._raises = raises
        self.calls: list[dict] = []

    def invoke(self, args: dict) -> object:
        self.calls.append(dict(args))
        if self._delay:
            time.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        if callable(self._returns):
            return self._returns(args)
        return self._returns


class FakeLLM:
    """按脚本返回 `AIMessage` 的假模型。

    脚本里的每一项是 `AIMessage` 或 `None`（`None` = 超出脚本，返回「资料已足够」不再调工具）。
    """

    def __init__(self, script: list[AIMessage | None]):
        self._script = list(script)
        self.bound: list[object] = []
        self.rounds = 0

    def bind_tools(self, tools: list[object]) -> FakeLLM:
        self.bound = list(tools)
        return self

    def invoke(self, messages: list[object]) -> AIMessage:
        self.rounds += 1
        if self._script:
            nxt = self._script.pop(0)
        else:
            nxt = None
        if nxt is None:
            return AIMessage(content="资料已足够，不再调用工具。")
        return nxt


class FakeClock:
    """假时钟：按给定序列推进，序列用完后停在最后一个值。"""

    def __init__(self, values: list[float] | None = None):
        self._values = list(values or [])
        self._last = 0.0

    def __call__(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last


def _call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _search_hit(url: str = OTHER_URL, title: str = "示例文章") -> dict:
    return {"query": "q", "results": [{"title": title, "url": url, "content": "检索到的片段"}]}


def _extract_hit(url: str = OTHER_URL, raw: str = "整页正文内容") -> dict:
    return {"results": [{"title": "示例页面", "url": url, "raw_content": raw}], "failed_results": []}


def _run(request: SearchRequest, llm: FakeLLM, search: FakeTool, extract: FakeTool, **kwargs: object):
    return run_search_agent(
        request,
        settings=kwargs.pop("settings", _settings()),
        llm=llm,
        tools=(search, extract),
        caps=kwargs.pop("caps", CAPS),
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- ① 正常收尾
def test_one_search_call_then_model_stops() -> None:
    """模型调一次 search 后不再要工具 → 正常收尾，资料被采到。"""
    llm = FakeLLM([_call("tavily_search", {"query": "q"}), None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", _extract_hit())

    outcome = _run(SearchRequest(query="Harness Engineering"), llm, search, extract)

    assert search.calls == [{"query": "q"}]
    assert extract.calls == []
    assert outcome.end_reason == "done"
    assert outcome.hit_count == 1
    assert outcome.degraded is False
    assert outcome.rounds_used == 2, "第一轮要工具、第二轮说够了"
    assert outcome.tool_calls_used == 1


def test_extract_call_is_also_a_valid_choice() -> None:
    """模型也可以直接选 extract（按用户给的链接或它自己判断的权威原文）。"""
    llm = FakeLLM([_call("tavily_extract", {"urls": [OTHER_URL]}), None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", _extract_hit())

    outcome = _run(SearchRequest(query="按这个页面出题"), llm, search, extract)

    assert extract.calls == [{"urls": [OTHER_URL]}]
    assert search.calls == []
    assert outcome.hit_count == 1
    assert outcome.results[0].kind == "page"


# ---------------------------------------------------------------- ② 第一轮就不要工具
def test_no_tool_calls_ends_immediately() -> None:
    """模型第一轮就不要工具 → 立刻收尾，**不浪费轮次**。"""
    llm = FakeLLM([None, _call("tavily_search", {"query": "不该存在"})])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", _extract_hit())

    outcome = _run(SearchRequest(query="什么是 RAG"), llm, search, extract)

    assert llm.rounds == 1, "只调了一次模型"
    assert outcome.end_reason == "no_tool_calls"
    assert outcome.rounds_used == 1
    assert search.calls == []


# ---------------------------------------------------------------- ③④ 上限触顶
def test_round_limit_stops_the_loop_and_is_named_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """轮次上限触顶 → 停止，并留一条**含上限名**的日志。"""
    llm = FakeLLM([_call("tavily_search", {"query": f"q{i}"}) for i in range(9)])
    search = FakeTool("tavily_search", lambda args: _search_hit(url=f"https://{args['query']}.example"))
    extract = FakeTool("tavily_extract", _extract_hit())

    with caplog.at_level(logging.WARNING):
        outcome = _run(
            SearchRequest(query="Harness Engineering"),
            llm,
            search,
            extract,
            settings=_settings(search_agent_max_rounds=2),
        )

    assert llm.rounds == 2, "上限是 2 轮，就不该调第三次"
    assert outcome.end_reason == "rounds_exhausted"
    assert outcome.rounds_used == 2
    assert outcome.limit_hit == "rounds_exhausted"
    assert any("rounds_exhausted" in r.getMessage() for r in caplog.records), (
        "触顶必须在日志里点名，否则「这次为什么只搜到 2 条」只能靠猜"
    )


def test_tool_call_limit_stops_within_a_round(caplog: pytest.LogCaptureFixture) -> None:
    """工具调用次数上限触顶 → 同一轮里剩下的调用也不再执行。"""
    # 一轮里就要 3 次调用，但上限是 2
    llm = FakeLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "tavily_search", "args": {"query": "a"}, "id": "c1", "type": "tool_call"},
                    {"name": "tavily_search", "args": {"query": "b"}, "id": "c2", "type": "tool_call"},
                    {"name": "tavily_search", "args": {"query": "c"}, "id": "c3", "type": "tool_call"},
                ],
            )
        ]
    )
    search = FakeTool("tavily_search", lambda args: _search_hit(url=f"https://{args['query']}.example"))
    extract = FakeTool("tavily_extract", _extract_hit())

    with caplog.at_level(logging.WARNING):
        outcome = _run(
            SearchRequest(query="Harness Engineering"),
            llm,
            search,
            extract,
            settings=_settings(search_agent_max_tool_calls=2),
        )

    assert [c["query"] for c in search.calls] == ["a", "b"], "第三次调用不该发生"
    assert outcome.end_reason == "tool_calls_exhausted"
    assert outcome.tool_calls_used == 2
    assert any("tool_calls_exhausted" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- ⑤ 总时长兜底
def test_deadline_stops_further_calls_and_keeps_what_was_collected() -> None:
    """越过总时长上限 → **不再发起新调用**，但已有资料照样收下（有资料 ⇒ 不是降级）。"""
    llm = FakeLLM([_call("tavily_search", {"query": "第一轮"}), _call("tavily_search", {"query": "第二轮"})])
    search = FakeTool("tavily_search", lambda args: _search_hit(url=f"https://{args['query']}.example"))
    extract = FakeTool("tavily_extract", _extract_hit())
    # 第 1 次（算 deadline）与第 2、3 次（第一轮）都还早，第 4 次之后判超时
    clock = FakeClock([0.0, 0.0, 0.5, 0.5, 99.0, 99.0])

    outcome = _run(
        SearchRequest(query="Harness Engineering"),
        llm,
        search,
        extract,
        settings=_settings(search_agent_budget_seconds=20),
        clock=clock,
    )

    assert [c["query"] for c in search.calls] == ["第一轮"], "第二轮不该被发出去"
    assert outcome.end_reason == "budget_exhausted"
    assert outcome.hit_count == 1, "已经取到的资料要留下"
    assert outcome.degraded is False


def test_deadline_before_first_call_returns_degraded_without_exception() -> None:
    """一开工就已超时 → 空手而归、`degraded=True`，且**不抛异常**。"""
    llm = FakeLLM([_call("tavily_search", {"query": "q"})])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", _extract_hit())
    clock = FakeClock([0.0, 99.0, 99.0, 99.0])

    outcome = _run(
        SearchRequest(query="Harness Engineering"),
        llm,
        search,
        extract,
        settings=_settings(search_agent_budget_seconds=20),
        clock=clock,
    )

    assert search.calls == []
    assert outcome.degraded is True
    assert outcome.end_reason == "budget_exhausted"


# ---------------------------------------------------------------- ⑥ 进度回调
def test_progress_callback_fires_before_and_after_each_call() -> None:
    """每次工具调用**前后各回调一次**，且文案含动作与数量（取材要跑十几秒，进度条要动）。"""
    llm = FakeLLM([_call("tavily_search", {"query": "q"}), _call("tavily_extract", {"urls": [OTHER_URL]}), None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", _extract_hit())
    seen: list[ToolProgress] = []

    _run(SearchRequest(query="Harness Engineering"), llm, search, extract, on_progress=seen.append)

    assert len(seen) == 4, "2 次调用 × (前 + 后)"
    assert [p.phase for p in seen] == ["start", "done", "start", "done"]
    assert [p.tool for p in seen] == ["tavily_search", "tavily_search", "tavily_extract", "tavily_extract"]
    for p in seen:
        assert p.detail, "每一步都要有给用户看的话"
        assert str(p.count) in p.detail, "文案要带上数量"
    assert seen[2].count == 1, "extract 的数量是网页数"


def test_progress_reports_failure_when_the_tool_raises() -> None:
    """工具抛异常时回调的是 `failed`，而不是假装成功。"""
    llm = FakeLLM([_call("tavily_search", {"query": "q"}), None])
    search = FakeTool("tavily_search", raises=RuntimeError("boom"))
    extract = FakeTool("tavily_extract", _extract_hit())
    seen: list[ToolProgress] = []

    outcome = _run(SearchRequest(query="Harness Engineering"), llm, search, extract, on_progress=seen.append)

    assert [p.phase for p in seen] == ["start", "failed"]
    assert outcome.degraded is True, "全部调用都失败 ⇒ 没有任何资料"


# ---------------------------------------------------------------- 超时（4.3）
def test_slow_call_is_abandoned_and_the_loop_continues() -> None:
    """单次调用超过 `search_tool_timeout_seconds` → 放弃该次，循环继续。"""
    llm = FakeLLM(
        [
            _call("tavily_search", {"query": "慢的"}, "c1"),
            _call("tavily_search", {"query": "快的"}, "c2"),
            None,
        ]
    )
    search = FakeTool("tavily_search", raises=None, delay=1.6)  # 第一次慢
    slow_then_fast = FakeTool("tavily_search")
    calls = {"n": 0}

    def _respond(args: dict) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(1.6)
        return _search_hit(url=f"https://{args['query']}.example")

    slow_then_fast._returns = _respond  # type: ignore[attr-defined]
    extract = FakeTool("tavily_extract", _extract_hit())

    outcome = _run(
        SearchRequest(query="Harness Engineering"),
        llm,
        slow_then_fast,
        extract,
        settings=_settings(search_tool_timeout_seconds=1),
    )
    assert search.calls == []
    assert outcome.end_reason == "done"
    assert outcome.tool_calls_used == 2, "超时的那次也算消耗了一次调用额度"
    assert outcome.hit_count == 1, "只有第二次取到了资料"
    assert outcome.degraded is False


def test_all_calls_timing_out_degrades_without_raising() -> None:
    """全部调用都超时 → `degraded=True` 且不抛异常。"""
    llm = FakeLLM([_call("tavily_search", {"query": "q1"}), _call("tavily_search", {"query": "q2"}), None])
    search = FakeTool("tavily_search", _search_hit(), delay=1.6)
    extract = FakeTool("tavily_extract", _extract_hit())

    outcome = _run(
        SearchRequest(query="Harness Engineering"),
        llm,
        search,
        extract,
        settings=_settings(search_tool_timeout_seconds=1),
    )

    assert outcome.degraded is True
    assert outcome.results == ()
    assert outcome.end_reason == "done", "超时不该被当成循环失败，它只是这几次调用没成"


def test_extract_has_its_own_longer_timeout() -> None:
    """extract 与 search **不共用**超时：整页正文比一小段 JSON 慢得多。

    构造「extract 耗时 1.6s、`search_tool_timeout_seconds=1`」这个组合：
    两处若共用同一个上限，这次读取就会被放弃 —— 而它读的正是**用户自己贴的链接**，
    是本产品最不能失败的一条路径（design D4）。

    背景（2026-09-22 端到端实测，`docs/MVP开发计划.md` §12.4）：贴了 Wikipedia 链接
    出题时，`tavily_extract` 连续两次撞在 8s。」（实测该页正文 7.4 万字符）
    """
    llm = FakeLLM([None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", lambda args: _extract_hit(url=args["urls"][0]), delay=1.6)

    outcome = _run(
        SearchRequest(query="读这个", urls=(USER_URL,)),
        llm,
        search,
        extract,
        settings=_settings(search_tool_timeout_seconds=1, search_extract_timeout_seconds=5),
    )

    assert extract.calls, "用户给的链接必须被读（服务端兜底）"
    assert outcome.hit_count == 1, "读到了正文，不该按超时放弃"
    assert outcome.degraded is False


def test_tool_pool_is_bounded() -> None:
    """超时后线程不会被回收，所以池**必须是有界的** —— 否则连续卡死会把进程拖垮（D12）。"""
    assert agent_module.TOOL_POOL_MAX_WORKERS == 4
    pool = agent_module.get_tool_pool()
    assert pool._max_workers == agent_module.TOOL_POOL_MAX_WORKERS  # noqa: SLF001 - 就是要断言这个上界


# ---------------------------------------------------------------- 链接兜底（4.5）
def test_user_urls_are_read_even_if_the_model_never_asks() -> None:
    """模型一轮都不调工具，用户给的链接**仍会被读**（服务端兜底）。"""
    llm = FakeLLM([None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", lambda args: _extract_hit(url=args["urls"][0]))

    outcome = _run(SearchRequest(query=f"按这个页面出题 {USER_URL}", urls=(USER_URL,)), llm, search, extract)

    assert extract.calls == [{"urls": [USER_URL]}], "兜底必须真的发生"
    assert outcome.hit_count == 1
    assert outcome.results[0].source == "user"
    assert outcome.results[0].kind == "page"


def test_fallback_and_model_extract_do_not_duplicate() -> None:
    """模型自己又读了一遍同一批 URL → 不与兜底结果重复（按 URL 去重）。"""
    llm = FakeLLM([_call("tavily_extract", {"urls": [USER_URL]}), None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", lambda args: _extract_hit(url=args["urls"][0]))

    outcome = _run(SearchRequest(query=f"按这个出题 {USER_URL}", urls=(USER_URL,)), llm, search, extract)

    assert len(extract.calls) == 2, "兜底一次 + 模型一次，两次都发生了"
    assert outcome.hit_count == 1, "但只留一条资料"


def test_search_is_disabled_but_the_link_is_still_read() -> None:
    """`use_search=False` → 不调用 search，但仍调用 extract（决策 3）。"""
    llm = FakeLLM([None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", lambda args: _extract_hit(url=args["urls"][0]))

    outcome = _run(
        SearchRequest(query=f"按这个出题 {USER_URL}", urls=(USER_URL,), use_search=False),
        llm,
        search,
        extract,
    )

    assert search.calls == [], "关掉搜索就不该有任何搜索调用"
    assert len(extract.calls) == 1
    assert outcome.hit_count == 1


def test_search_tool_is_not_even_offered_when_search_is_off() -> None:
    """更深一层：关掉搜索时连工具都不该绑定给模型 —— 让「不该发生」变成「不可能发生」。"""
    llm = FakeLLM([None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", lambda args: _extract_hit(url=args["urls"][0]))

    _run(
        SearchRequest(query=f"按这个出题 {USER_URL}", urls=(USER_URL,), use_search=False),
        llm,
        search,
        extract,
    )

    assert [getattr(t, "name", None) for t in llm.bound] == ["tavily_extract"]


# ---------------------------------------------------------------- 完全不该碰网络
def test_no_external_intent_returns_disabled_without_touching_anything() -> None:
    """开关关 + 没链接 → 一次工具都不调、一次模型都不调（`disabled`）。"""
    llm = FakeLLM([None])
    search = FakeTool("tavily_search", _search_hit())
    extract = FakeTool("tavily_extract", _extract_hit())

    outcome = _run(SearchRequest(query="什么是 RAG", use_search=False), llm, search, extract)

    assert llm.rounds == 0
    assert search.calls == []
    assert extract.calls == []
    assert outcome.end_reason == "disabled"
    assert outcome.degraded is True
    assert outcome.step_name == "理解你的输入"


def test_loop_never_raises_even_if_the_model_blows_up() -> None:
    """模型本身抛异常也不能把出题拖垮 —— 契约是「gather 不抛异常」。"""

    class ExplodingLLM(FakeLLM):
        def invoke(self, messages: list[object]) -> AIMessage:
            raise RuntimeError("model exploded")

    outcome = _run(
        SearchRequest(query="Harness Engineering"),
        ExplodingLLM([]),
        FakeTool("tavily_search", _search_hit()),
        FakeTool("tavily_extract", _extract_hit()),
    )

    assert outcome.degraded is True
    assert outcome.end_reason == "error"


# ---------------------------------------------------------------- 与模型互动的措辞
def test_human_message_lists_the_user_urls_explicitly() -> None:
    """有链接时，第一条 Human Message 必须**显式列出**这些 URL 并指示先读（design D4）。"""
    captured: list[object] = []

    class CapturingLLM(FakeLLM):
        def invoke(self, messages: list[object]) -> AIMessage:
            captured.append(messages)
            return super().invoke(messages)

    _run(
        SearchRequest(query=f"按这个出题 {USER_URL}", urls=(USER_URL,)),
        CapturingLLM([None]),
        FakeTool("tavily_search", _search_hit()),
        FakeTool("tavily_extract", lambda args: _extract_hit(url=args["urls"][0])),
    )

    first = captured[0]
    joined = "\n".join(str(getattr(m, "content", m)) for m in first)  # type: ignore[union-attr]
    assert USER_URL in joined
    assert "先读" in joined or "先读取" in joined, "要明确指示优先读这些链接"


def test_model_only_sees_a_bounded_copy_of_tool_results() -> None:
    """回喂给模型的工具结果**必须截断**：实测单页 7.5 万字符，原样回喂会撑爆上下文。"""
    captured: list[object] = []

    class CapturingLLM(FakeLLM):
        def invoke(self, messages: list[object]) -> AIMessage:
            captured.append(list(messages))
            return super().invoke(messages)

    huge = "字" * 50_000
    llm = CapturingLLM([_call("tavily_extract", {"urls": [OTHER_URL]}), None])
    extract = FakeTool("tavily_extract", _extract_hit(raw=huge))

    _run(SearchRequest(query="按这个页面出题"), llm, FakeTool("tavily_search", _search_hit()), extract)

    # 第二轮的消息里包含那条 ToolMessage
    second_round = captured[1]
    tool_messages = [m for m in second_round if getattr(m, "type", "") == "tool"]  # type: ignore[union-attr]
    assert tool_messages, "工具结果必须回喂给模型，否则它无法决定下一步"
    assert len(str(tool_messages[-1].content)) < 20_000  # type: ignore[union-attr]
    assert "截断" in str(tool_messages[-1].content)  # type: ignore[union-attr]


def test_collected_page_keeps_the_full_body_despite_the_bounded_copy() -> None:
    """截断只作用于「给模型看的那份」，采集到的那份仍按整页上限处理。"""
    huge = "词" * 3000
    llm = FakeLLM([_call("tavily_extract", {"urls": [OTHER_URL]}), None])
    extract = FakeTool("tavily_extract", _extract_hit(raw=huge))

    outcome = _run(SearchRequest(query="按这个页面出题"), llm, FakeTool("tavily_search", _search_hit()), extract)

    assert len(outcome.results[0].snippet) == CAPS.page_max_chars + len(" …（已截断）")
