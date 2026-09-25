"""`NoopSearchProvider` 与知识库（`add-private-knowledge-base` 第 8 组，8.7）。

## 为什么它需要单独一份文件

`test_search_provider.py` 守的是「Noop 什么都不做」：不联网、不发请求、
不讲自己没能力讲的话。那份契约今天仍然成立 —— **但它只对不带库的请求成立**。

本文件加的是另一半（design D8）：`KNOWLEDGE_SEARCH_ENABLED=false` 是**默认配置**，
而它是「只用我自己的资料出题」这个诉求唯一会走到的路径。不改 Noop 的话，
用户选了自己的库、上传解析好，出题时却一条资料都拿不到 ——
而且日志上写着「取材未启用」，看起来完全正常。这就是典型的**静默失败**，
所以它必须有一条专门的用例盯着。

## 与另外两份文件的分工

| 文件 | 管什么 |
|---|---|
| `test_search_provider.py` | Noop 不带库时的既有契约（逐位不变） |
| `test_search_agent_kb.py` | 带库时有界循环的形状（工具绑定 / 上限 / 进度 / 文案） |
| **本文件** | Noop 这个 **Provider** 在带库请求上的行为与 `initial_step` |

这里用替身换掉 `build_kb_tool`：本文件验的是**接线**（带库 ⇒ 真的去调那个工具），
「真的能查到、且只查到自己那一个库」由 `test_kb_tool.py` 用真库 + 真 Chroma 钉住 ——
把那份职责重复一遍只会让两处都变成维护负担。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from app.core.config import Settings
from app.llm.search import get_search_provider
from app.llm.search.base import KB_TOOL_NAME, KbScope, SearchOutcome, SearchRequest
from app.llm.search.noop import NoopSearchProvider

SCOPE = KbScope(user_id=3, kb_id=7)
WITH_KB = SearchRequest(query="监督学习", kb=SCOPE)
WITH_KB_SEARCH_ON = SearchRequest(query="监督学习", kb=SCOPE, use_search=True)
PLAIN = SearchRequest(query="监督学习", use_search=False)


def _settings(**overrides: object) -> Settings:
    # `knowledge_base_enabled` 默认是 `False`（config 里的部署默认值）。
    # 但**本文件整份都在「知识库已开启」的前提下**：`initial_step` 现在会读这个开关
    # 决定说不说「检索你的知识库」（design D7），所以这里必须显式打开 ——
    # 忘了它会让下面那两条 initial_step 断言静默地退化成「理解你的输入」。
    base: dict[str, object] = {"knowledge_search_enabled": False, "knowledge_base_enabled": True}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


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
        return AIMessage(content="资料已足够。") if nxt is None else nxt


def _call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}]
    )


def _kb_hit() -> dict:
    return {
        "query": "q",
        "results": [
            {
                "title": "机器学习讲义.md",
                "url": "kb://7/12#0",
                "content": "监督学习是从标注数据中学习映射函数。",
                "source": "kb",
                "kind": "snippet",
            }
        ],
    }


@pytest.fixture
def fake_kb_tool(monkeypatch: pytest.MonkeyPatch) -> FakeTool:
    """把知识库工具换成替身（`noop` 是惰性 import 它，所以 patch 模块属性即可）。"""
    tool = FakeTool(KB_TOOL_NAME, _kb_hit())
    monkeypatch.setattr("app.llm.kb.tools.build_kb_tool", lambda request, settings: tool)
    return tool


@pytest.fixture
def spy_agent(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """把取材循环换成**窥探替身**，只记录「交进去的是什么」。

    ⚠️ 工厂那两条用例**不能**真跑 `gather()`：`get_search_provider()` 返回的对象
    没有 `llm` 注入口，真跑就会在 `run_search_agent` 里走
    `build_chat_model()` 发一次**真实模型请求**（测试红线）。

    `noop.gather()` 里的 `from app.llm.search.agent import run_search_agent` 是
    调用时才执行的，所以 patch 模块属性就够 —— 不需要 patch `noop` 自己的命名空间。
    """

    def _fake(request: SearchRequest, **kwargs: object) -> SearchOutcome:
        calls.append({"request": request, **kwargs})
        return SearchOutcome(
            provider=str(kwargs.get("provider_name") or "none"),
            step_name="检索你的知识库",
            results=(),
            end_reason="done",
        )

    calls: list[dict] = []
    monkeypatch.setattr("app.llm.search.agent.run_search_agent", _fake)
    return calls


# ---------------------------------------------------------------- 带库：真的去查
def test_noop_gather_actually_searches_the_users_base(fake_kb_tool: FakeTool) -> None:
    """带库 ⇒ 真的调 kb 工具。**这条就是 design D8 要修的静默失败。**"""
    provider = NoopSearchProvider(
        _settings(), llm=FakeLLM([_call(KB_TOOL_NAME, {"query": "监督学习"}), None])
    )

    outcome = provider.gather(WITH_KB)

    assert fake_kb_tool.calls == [{"query": "监督学习"}]
    assert outcome.hit_count == 1
    assert outcome.end_reason == "done"
    assert outcome.results[0].source == "kb"


def test_noop_binds_only_the_kb_tool(fake_kb_tool: FakeTool) -> None:
    """它没有任何联网工具 ⇒ 绑给模型的**只有** kb 那一个。

    绑上空名字会让模型去调一个不存在的工具，而每次拒绝都要多烧一轮预算。
    """
    llm = FakeLLM([None])

    NoopSearchProvider(_settings(), llm=llm).gather(WITH_KB)

    assert [getattr(t, "name", None) for t in llm.bound] == [KB_TOOL_NAME]


def test_noop_kb_path_does_not_need_a_search_key(fake_kb_tool: FakeTool) -> None:
    """`tools=(None, None)` 而不是 `tools=None`。

    `tools=None` 会去 `build_tavily_tools()` 要 `TAVILY_API_KEY` ——
    那等于把「没开联网」变成一次 5000 配置错误，而这条路径本来完全不需要联网。
    """
    provider = NoopSearchProvider(_settings(tavily_api_key=""), llm=FakeLLM([None]))

    outcome = provider.gather(WITH_KB)

    assert outcome.provider == "none"


# ---------------------------------------------------------------- 不带库：逐位不变
def test_noop_without_a_base_stays_disabled() -> None:
    """不带库 ⇒ 一次模型都不调、一次外部调用都不发（与今天逐位一致）。"""
    llm = FakeLLM([None])

    outcome = NoopSearchProvider(_settings(), llm=llm).gather(PLAIN)

    assert llm.rounds == 0
    assert outcome.end_reason == "disabled"
    assert outcome.hit_count == 0
    assert outcome.degraded is True


def test_noop_without_settings_still_works() -> None:
    """既有的 `NoopSearchProvider()` 无参调用不许坏（design D8 明写）。

    不带库时它连 `settings` 都不该碰 —— 碰了就要在 `gather()` 里取全局单例，
    而这会让「只读一个返回值」的用例悄悄依赖开发者的本地 `.env`。
    """
    outcome = NoopSearchProvider().gather(PLAIN)

    assert outcome.end_reason == "disabled"


# ---------------------------------------------------------------- initial_step
def test_initial_step_names_the_base_only_when_one_is_given() -> None:
    """带库说「检索你的知识库」，不带库仍是「理解你的输入」。

    两个方向都要钉：前者是「别把这次做的事说成没做」，
    后者是「没有能力就不许显示能力」那条既有契约（冲突点 14）。
    """
    provider = NoopSearchProvider(_settings())

    assert provider.initial_step(WITH_KB).name == "检索你的知识库"
    assert provider.initial_step(WITH_KB).detail
    assert provider.initial_step(PLAIN).name == "理解你的输入"


def test_initial_step_name_matches_the_gather_outcome(fake_kb_tool: FakeTool) -> None:
    """`gather()` 盖上的 `step_name` 必须与开工前给前端看的那一个**同名**。

    不同名的表现是：进度卡上写着「检索你的知识库」，几秒后回来的结果里
    那一步忽然变成「理解你的输入」—— 用户会以为我们偷偷跳过了他的资料。
    """
    provider = NoopSearchProvider(_settings(), llm=FakeLLM([None]))

    outcome = provider.gather(WITH_KB)

    assert outcome.step_name == provider.initial_step(WITH_KB).name


def test_feature_switch_off_hides_the_kb_step_even_with_a_base() -> None:
    """**开关关掉时，带了库也不许预告「检索你的知识库」**（design D7）。

    此时 `build_kb_tool()` 返回 `None`，一次检索都不会发生。
    还说「检索你的知识库」就是在讲一件不会发生的事 ——
    正是红线「文案与实现冲突时改文案」要挡的那种。
    """
    off = _settings(knowledge_base_enabled=False)
    provider = NoopSearchProvider(off)

    assert provider.initial_step(WITH_KB).name == "理解你的输入"


def test_feature_switch_off_does_not_search_the_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关掉时，**真的**一次 kb 工具都不绑（不只是文案变了）。

    这条与上一条合起来才完整：只改文案而工具照建，用户会看到
    「理解你的输入」的进度卡，但后台其实查了向量库 —— 更隐蔽的错。

    这里**不**用 `fake_kb_tool` 替身：要验的正好是真的 `build_kb_tool` 在开关
    关掉时返回 `None` 这条行为，替换掉它就把要验的东西替没了。
    """
    off = _settings(knowledge_base_enabled=False)
    llm = FakeLLM([None])

    outcome = NoopSearchProvider(off, llm=llm).gather(WITH_KB)

    assert llm.bound == [], "没有任何工具可绑（kb 关掉、联网也没开）"
    assert outcome.step_name == "理解你的输入"
    assert outcome.degraded is True


# ---------------------------------------------------------------- provider 工厂
def test_factory_hands_settings_to_the_noop_provider(spy_agent: list[dict]) -> None:
    """`get_search_provider()` 要把 settings 传进 Noop（8.8 的另一半）。

    不传的话 Noop 在带库时会去取全局单例配置 —— 而工厂本来就是按**传进来的**
    settings 做判断的，两处一旦不一致，出现的就是「按 A 配置判断、按 B 配置执行」。

    ⚠️ 这里不能真跑 `gather()`：工厂返回的对象没有 llm 注入口，真跑就会去
    `build_chat_model()` 发一次**真实模型请求**（测试红线）。所以把 `run_search_agent`
    换成窥探替身，只验「交进去的是什么」。
    """
    from app.llm.search.noop import NoopSearchProvider as _Noop

    settings = _settings(knowledge_search_enabled=False)
    provider = get_search_provider(settings)

    assert isinstance(provider, _Noop)
    provider.gather(WITH_KB)

    assert len(spy_agent) == 1, "带库的请求必须走到取材循环里"
    assert spy_agent[0]["settings"] is settings, "必须是工厂手里那一份配置"
    assert spy_agent[0]["tools"] == (None, None), "它一个联网工具都没有"


def test_factory_still_returns_noop_for_the_none_name(spy_agent: list[dict]) -> None:
    """`KNOWLEDGE_SEARCH_PROVIDER=none` 与开关关掉是同一件事，两条路都要带 settings。"""
    settings = _settings(knowledge_search_enabled=True, knowledge_search_provider="none")

    provider = get_search_provider(settings)
    provider.gather(WITH_KB_SEARCH_ON)

    assert spy_agent[0]["settings"] is settings

