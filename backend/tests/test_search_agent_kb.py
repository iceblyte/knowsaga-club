"""带知识库时的取材循环（`add-private-knowledge-base` 第 8 组）。

## 与 `test_search_agent.py` 的关系

那份文件钉的是**有界循环本身**（轮次 / 次数 / 时长 / 超时 / 链接兜底），
每一项都是与「几个工具」无关的性质。本文件只加一件事：
**第三个工具（`kb_search`）在这套上限里怎么表现** —— 它必须与另外两个
受同一套约束，而不是自己另有一套。

所以这里的假模型与假工具刻意重写了一份小号实现，不去动那份已交付的测试文件。
它要验的四件事：

1. **只在本请求带了库时才绑** kb 工具。不带库的请求绑上去，模型就会去调，
   而库里没有本次要用的资料 —— 用户会拿到一份莫名其妙的题。
2. `use_search=False`（用户关掉联网）**不影响** kb 搜索：kb 不是联网，
   这两件事本来就无关（design D7 的落点之一）。
3. kb 调用**受同一套次数与时长上限**约束：「多搜几次自己的资料」同样会烧预算。
4. **没有联网工具时仍能跑**（Noop 路径的形状，design D8）：
   `tools=(None, None)` + 带库 ⇒ 只绑 kb 工具，循环照跑。
"""

from __future__ import annotations

import logging

import pytest
from langchain_core.messages import AIMessage

from app.core.config import Settings
from app.llm.search import agent as agent_module
from app.llm.search.agent import ToolProgress, describe_step, run_search_agent
from app.llm.search.base import (
    KB_TOOL_NAME,
    KbScope,
    ReferenceCaps,
    SearchOutcome,
    SearchRequest,
    build_initial_step,
)
from app.prompts.search_prompt import build_agent_messages

USER_URL = "https://user.example/page"
OTHER_URL = "https://other.example/post"

SCOPE = KbScope(user_id=3, kb_id=7)
WITH_KB = SearchRequest(query="监督学习", kb=SCOPE)
WITH_KB_NO_WEB = SearchRequest(query="监督学习", kb=SCOPE, use_search=False)
PLAIN = SearchRequest(query="监督学习")


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "knowledge_search_enabled": True,
        "knowledge_search_provider": "tavily",
        "tavily_api_key": "test-key",
        # 本文件整份都在「知识库已开启」的前提下（config 里的部署默认是关）。
        # `describe_step` 会读它，忘掉它会让第 ⑦ 组的断言静默失去意义。
        "knowledge_base_enabled": True,
        "search_agent_max_rounds": 3,
        "search_agent_max_tool_calls": 4,
        "search_agent_budget_seconds": 20,
        "search_tool_timeout_seconds": 1,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


CAPS = ReferenceCaps(snippet_max_chars=200, page_max_chars=300, total_max_chars=2000)


class FakeTool:
    def __init__(self, name: str, returns: object = None) -> None:
        self.name = name
        self._returns = returns
        self.calls: list[dict] = []

    def invoke(self, args: dict) -> object:
        self.calls.append(dict(args))
        return self._returns


class FakeLLM:
    def __init__(self, script: list[AIMessage | None]) -> None:
        self._script = list(script)
        self.bound: list[object] = []
        self.rounds = 0

    def bind_tools(self, tools: list[object]) -> FakeLLM:
        self.bound = list(tools)
        return self

    def invoke(self, messages: list[object]) -> AIMessage:
        self.rounds += 1
        nxt = self._script.pop(0) if self._script else None
        return AIMessage(content="资料已足够，不再调用工具。") if nxt is None else nxt


def _call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}]
    )


def _kb_hit(text: str = "监督学习是从标注数据中学习映射函数。") -> dict:
    return {
        "query": "q",
        "results": [
            {
                "title": "机器学习讲义.md",
                "url": "kb://7/12#0",
                "content": text,
                "source": "kb",
                "kind": "snippet",
                "filename": "机器学习讲义.md",
                "chunk_index": 0,
            }
        ],
    }


def _bound_names(llm: FakeLLM) -> list[str]:
    return [getattr(tool, "name", None) for tool in llm.bound]


def _run(request: SearchRequest, llm: FakeLLM, *, kb_tool: object = None, **kwargs: object):  # noqa: ANN201
    """跑一轮取材。默认注入「两个联网工具都不可用」的形状，再单独给 kb 工具。"""
    return run_search_agent(
        request,
        settings=kwargs.pop("settings", _settings()),
        llm=llm,
        tools=kwargs.pop("tools", (None, None)),
        kb_tool=kb_tool,
        caps=kwargs.pop("caps", CAPS),
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- ① 绑定
def test_kb_tool_is_bound_when_a_base_is_requested() -> None:
    """带了库、又没有联网工具 ⇒ 只绑 kb。"""
    llm = FakeLLM([None])

    _run(WITH_KB, llm, kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()))

    assert _bound_names(llm) == [KB_TOOL_NAME]


def test_kb_tool_is_absent_without_a_base() -> None:
    """不带库 ⇒ 哪怕注入了一个 kb 工具也**不许绑**。

    绑上去模型就会去调，而库里没有本次要用的资料 —— 用户会拿到一份莫名其妙的题。
    """
    llm = FakeLLM([None])
    search = FakeTool("tavily_search")
    extract = FakeTool("tavily_extract")

    _run(PLAIN, llm, tools=(search, extract), kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()))

    assert _bound_names(llm) == ["tavily_search", "tavily_extract"]


def test_kb_tool_joins_the_web_tools_when_both_are_available() -> None:
    """联网工具与 kb 工具可以同时在场（本机默认配置就是这种组合）。"""
    llm = FakeLLM([None])
    search = FakeTool("tavily_search")
    extract = FakeTool("tavily_extract")

    _run(WITH_KB, llm, tools=(search, extract), kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()))

    assert _bound_names(llm) == ["tavily_search", "tavily_extract", KB_TOOL_NAME]


def test_kb_search_survives_use_search_false() -> None:
    """关掉联网搜索**不影响** kb 搜索 —— kb 不是联网。

    `use_search=False` 时 `tavily_search` 连绑都不绑（既有设计：
    让「不该发生」变成「不可能发生」），但 kb 必须照常可用，
    否则「只用我自己的资料出题」这个诉求根本没法表达。
    """
    llm = FakeLLM([_call(KB_TOOL_NAME, {"query": "监督学习"}), None])
    kb_tool = FakeTool(KB_TOOL_NAME, _kb_hit())

    outcome = _run(WITH_KB_NO_WEB, llm, tools=(None, FakeTool("tavily_extract")), kb_tool=kb_tool)

    assert _bound_names(llm) == ["tavily_extract", KB_TOOL_NAME]
    assert kb_tool.calls == [{"query": "监督学习"}]
    assert outcome.hit_count == 1


# ---------------------------------------------------------------- ② 采集
def test_kb_hit_is_collected_as_kb_source() -> None:
    llm = FakeLLM([_call(KB_TOOL_NAME, {"query": "监督学习"}), None])

    outcome = _run(WITH_KB, llm, kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()))

    assert outcome.hit_count == 1
    assert outcome.results[0].source == "kb"
    assert outcome.results[0].kind == "snippet"
    assert outcome.results[0].url == "kb://7/12#0"
    assert outcome.degraded is False
    assert outcome.end_reason == "done"


def test_kb_call_counts_against_the_tool_call_limit(caplog: pytest.LogCaptureFixture) -> None:
    """kb 调用**消耗同一份额度** —— 「多搜几次自己的资料」同样会烧预算。"""
    llm = FakeLLM(
        [
            _call(KB_TOOL_NAME, {"query": "a"}, "c1"),
            _call(KB_TOOL_NAME, {"query": "b"}, "c2"),
            _call(KB_TOOL_NAME, {"query": "c"}, "c3"),
        ]
    )
    kb_tool = FakeTool(KB_TOOL_NAME, _kb_hit())

    with caplog.at_level(logging.WARNING):
        outcome = _run(
            WITH_KB, llm, kb_tool=kb_tool, settings=_settings(search_agent_max_tool_calls=2)
        )

    assert [c["query"] for c in kb_tool.calls] == ["a", "b"], "第三次调用不该发生"
    assert outcome.end_reason == "tool_calls_exhausted"
    assert outcome.tool_calls_used == 2
    assert any("tool_calls_exhausted" in r.getMessage() for r in caplog.records)


def test_kb_call_has_its_own_timeout_tier() -> None:
    """kb 与 `tavily_search` 同一档超时；**不是** extract 那一档。

    回传体积同量级（≤ 4 段 × 每段上限），慢的部分是它内部那次向量化调用，
    而不是「一页 7 万字符」。给它 extract 的 15s 会平白吃掉总预算。
    """
    settings = _settings()

    assert agent_module._timeout_for(KB_TOOL_NAME, settings) == settings.search_tool_timeout_seconds
    assert agent_module._call_count(KB_TOOL_NAME, {"query": "x"}) == 1


# ---------------------------------------------------------------- ③ 进度文案
def test_kb_progress_copy_carries_action_and_count() -> None:
    """进度文案要含**数量**并说清在做什么（沿用取材料的既有约定）。"""
    llm = FakeLLM([_call(KB_TOOL_NAME, {"query": "监督学习与无监督学习"}), None])
    seen: list[ToolProgress] = []

    _run(WITH_KB, llm, kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()), on_progress=seen.append)

    assert [p.tool for p in seen] == [KB_TOOL_NAME, KB_TOOL_NAME]
    assert [p.phase for p in seen] == ["start", "done"]
    for progress in seen:
        assert str(progress.count) in progress.detail
    assert "资料" in seen[0].detail, seen[0].detail
    assert "监督学习" in seen[0].detail, "把检索词带上，用户才知道在查什么"


def test_kb_progress_reports_failure_when_the_tool_returns_an_error() -> None:
    """工具返回错误体（不抛异常）时，进度也要说 `failed`。"""
    llm = FakeLLM([_call(KB_TOOL_NAME, {"query": "q"}), None])
    seen: list[ToolProgress] = []

    outcome = _run(
        WITH_KB,
        llm,
        kb_tool=FakeTool(KB_TOOL_NAME, {"query": "q", "error": "知识库检索失败"}),
        on_progress=seen.append,
    )

    assert [p.phase for p in seen] == ["start", "done"], "工具本身没抛异常，回调不该谎报失败"
    assert outcome.degraded is True, "但采集侧必须判成「没有资料」"


# ---------------------------------------------------------------- ④ 第一步文案
def test_initial_step_says_searching_your_kb() -> None:
    """带库的请求，第一步必须说「检索你的知识库」，而不是「联网检索知识」。"""
    step = build_initial_step(
        WITH_KB_NO_WEB, can_search_web=False, can_read_pages=False, can_search_kb=True
    )

    assert step.name == "检索你的知识库"
    assert step.detail, "每一步都要有给用户看的过程说明"


def test_outcome_step_name_matches_the_actual_capability() -> None:
    """`run_search_agent` 算出的第一步名字必须**与真的绑了什么工具一致**。

    这条守的是红线「文案与实现冲突时改文案」：没有联网工具时说「联网检索知识」，
    用户会以为在联网 —— 而那个 Provider 一次网络都不会碰。
    """
    llm = FakeLLM([None])

    outcome = _run(WITH_KB, llm, kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()))

    assert isinstance(outcome, SearchOutcome)
    assert outcome.step_name == "检索你的知识库", outcome.step_name


def test_no_kb_request_keeps_the_understand_input_step() -> None:
    """不带库的请求第一步不变（`use_search=False` 且无链接 ⇒ 「理解你的输入」）。

    这是「默认关 ⇒ 行为不变」在文案上的那一半。
    """
    llm = FakeLLM([None])
    request = SearchRequest(query="什么是 RAG", use_search=False)

    outcome = run_search_agent(
        request,
        settings=_settings(),
        llm=llm,
        tools=(FakeTool("tavily_search"), FakeTool("tavily_extract")),
        caps=CAPS,
    )

    assert outcome.step_name == "理解你的输入"
    assert outcome.end_reason == "disabled"
    assert llm.rounds == 0, "不带库又不想联网 ⇒ 一次模型都不该调"


# ---------------------------------------------------------------- ⑤ 无联网工具也能跑（Noop 形状）
def test_kb_only_request_runs_a_round_without_web_tools() -> None:
    """`tools=(None, None)` + 带库 ⇒ 循环照跑，只绑 kb（design D8 的形状）。

    这正是「只用知识库、不开联网」这个默认配置的路径：`get_search_provider()`
    返回 Noop，而 Noop 在带库时仍要真的去检索。不改它的话，用户选了自己的库、
    上传解析好，出题时却一条资料都拿不到，日志上看着还完全正常。
    """
    llm = FakeLLM([_call(KB_TOOL_NAME, {"query": "监督学习"}), None])
    kb_tool = FakeTool(KB_TOOL_NAME, _kb_hit())

    outcome = _run(WITH_KB_NO_WEB, llm, kb_tool=kb_tool)

    assert llm.rounds == 2, "第一轮要工具、第二轮说够了"
    assert kb_tool.calls == [{"query": "监督学习"}]
    assert outcome.hit_count == 1
    assert outcome.end_reason == "done"
    assert outcome.step_name == "检索你的知识库"


def test_no_web_tools_means_no_url_fallback() -> None:
    """没有 extract 工具时，**不做**链接兜底（用户给的链接这次读不了）。

    现有实现里兜底会无条件调 extract —— 而 Noop 的 `can_read_pages=False`，
    它根本没有那个工具。不跳过就是一次 `AttributeError: 'NoneType'`。
    """
    llm = FakeLLM([None])
    request = SearchRequest(query=f"按这个出题 {USER_URL}", urls=(USER_URL,), kb=SCOPE)

    outcome = _run(request, llm, kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()))

    assert outcome.hit_count == 0
    assert outcome.end_reason == "no_tool_calls"


def test_url_fallback_still_runs_when_extract_exists() -> None:
    """有 extract 时兜底照旧 —— 上一条不该把它一起关掉。"""
    llm = FakeLLM([None])
    extract = FakeTool("tavily_extract", {"results": [{"url": USER_URL, "raw_content": "正文"}]})
    request = SearchRequest(query=f"按这个出题 {USER_URL}", urls=(USER_URL,), kb=SCOPE)

    outcome = _run(
        request, llm, tools=(FakeTool("tavily_search"), extract), kb_tool=FakeTool(KB_TOOL_NAME)
    )

    assert extract.calls == [{"urls": [USER_URL]}], "有工具就必须读用户给的链接"
    assert outcome.hit_count == 1


# ---------------------------------------------------------------- ⑥ Prompt 里的工具说明
def test_messages_mention_kb_search_only_when_a_base_is_bound() -> None:
    """带库时要在给模型的话里**说出**这个工具（模型看不到我们的代码）。

    不写这一句，模型只能靠 `bind_tools` 给的 schema 猜它是干什么的 ——
    而它很可能把 `kb_search` 当成「又一个联网搜索」，
    于是拿到知识库片段后会按「网上的东西」对待，
    与训练数据冲突时倾向于推翻它（spec 要求相反：以用户自己的资料为准）。
    """
    with_kb = "\n".join(str(m.content) for m in build_agent_messages(WITH_KB, max_rounds=3))
    without = "\n".join(str(m.content) for m in build_agent_messages(PLAIN, max_rounds=3))

    assert KB_TOOL_NAME in with_kb
    assert KB_TOOL_NAME not in without, "不带库时不许提这个工具，否则模型会去调不存在的工具"


def test_human_message_explains_the_kb_scope_and_priority() -> None:
    """说明里必须有两件事：范围只有这一个库、与公开来源冲突时以它为准。"""
    human = str(build_agent_messages(WITH_KB, max_rounds=3)[1].content)

    assert "自己" in human or "上传" in human, human
    assert "库" in human, human
    assert "为准" in human or "优先" in human, "要给出冲突时的取向，否则模型自己权衡"


# ------------------------------------------- ⑦ 给 Provider 复用的第一步文案 + 开关
def test_describe_step_names_the_base_and_honours_the_switch() -> None:
    """`describe_step` 是 Tavily 的 `initial_step()` 唯一实现点，必须看**请求与开关**。

    优先级是「链接 > 联网 > 知识库 > 理解输入」（`build_initial_step`）。
    它硬编码了「这个 Provider 有联网能力」，所以带库的那一支只有在
    **用户没要联网**（`use_search=False`）时才轮得到 —— 那时该说
    「检索你的知识库」。开关关掉时必须退成「理解你的输入」：
    那时 `build_kb_tool()` 返回 `None`，一次检索都不会发生。
    """
    on = _settings()
    off = _settings(knowledge_base_enabled=False)

    assert describe_step(WITH_KB_NO_WEB, on).name == "检索你的知识库"
    assert describe_step(WITH_KB_NO_WEB, on).detail, "每一步都要有给用户看的过程说明"
    assert describe_step(WITH_KB_NO_WEB, off).name == "理解你的输入"


def test_describe_step_keeps_web_first_when_the_user_wants_search() -> None:
    """用户要联网时有网可联 ⇒ 说「联网检索知识」，而不是被知识库抢了先。

    这条挡的是「把知识库那一支提到最前面」这种改法 —— 那会让
    `KNOWLEDGE_SEARCH_ENABLED=true` 的部署再也不说自己在联网。
    """
    assert describe_step(WITH_KB, _settings()).name == "联网检索知识"


def test_describe_step_name_equals_the_gather_outcome_name() -> None:
    """`initial_step()` 给的名字必须与 `gather()` 回来时盖的名字**逐字相同**。

    不同名的表现是：进度卡上写着 A，几秒后结果里那一步忽然变成 B ——
    用户会以为我们偷偷跳过了他的资料。这里用「只带库、不联网」的形状
    （`tools=(None, None)`），因为那正是这条判定的边界所在。
    """
    settings = _settings()
    llm = FakeLLM([None])

    outcome = _run(
        WITH_KB_NO_WEB, llm, kb_tool=FakeTool(KB_TOOL_NAME, _kb_hit()), settings=settings
    )

    assert outcome.step_name == describe_step(WITH_KB_NO_WEB, settings).name == "检索你的知识库"
