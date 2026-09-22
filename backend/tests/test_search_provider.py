"""检索 Provider 的契约（`add-web-search-grounding` 第 2 组）。

本组**只演进契约、不改行为**：`NoopSearchProvider` 仍然是那条「不联网」的路径，
但它的接口从「一个 `step_name` 属性 + 一个 `search(query)` 方法」改成
「`initial_step(request)` + `gather(request)`」—— 因为第一步现在有**三种**名字，
而名字必须在开工前就展示给用户（见 design D8）。

## ⚠️ 与 `tasks.md` 2.1 ④ 的有意偏离（冲突点 14）

`tasks.md` 原文要求「`NoopSearchProvider` 的 `initial_step` 同样遵守三态」。
**照做会让文案说谎**：测试环境的 `KNOWLEDGE_SEARCH_ENABLED=false`，
用户不带 `use_search` 时（默认 `True`）第一步会显示「联网检索知识」，
而 Noop 一次网络都不会碰。这与项目红线「文案与实现冲突时改文案，不假装兑现」直接冲突，
也会打破已交付并被看护的 `test_quiz_api.test_first_step_name_comes_from_search_provider`。

因此三态判定把**能力**一并算进去（`build_initial_step` 的两个 `can_*` 开关），
Noop 的能力全为假 ⇒ 它永远显示「理解你的输入」；真正能联网的 Provider 才拿得到另两个名字。

运行期不发任何外部请求：本文件的用例都只碰 `NoopSearchProvider`。
"""

from __future__ import annotations

import socket

import pytest

from app.core.config import Settings
from app.llm.search import NoopSearchProvider
from app.llm.search.base import (
    ReferenceCaps,
    SearchOutcome,
    SearchProvider,
    SearchRequest,
    SearchResult,
    build_initial_step,
)

#: 用户贴了链接的输入（第 7 组会加真正的链接抽取函数，这里先直接给 `urls`）
WITH_URLS = SearchRequest(
    query="帮我按这个页面出题 https://example.com/a",
    urls=("https://example.com/a",),
)
WITHOUT_URLS_SEARCH_ON = SearchRequest(query="什么是 Harness Engineering", use_search=True)
WITHOUT_URLS_SEARCH_OFF = SearchRequest(query="什么是 Harness Engineering", use_search=False)


# ---------------------------------------------------------------- SearchRequest
def test_search_request_defaults() -> None:
    """`SearchRequest` 的字段与默认值。

    `use_search` 默认 `True`：用户没表态时按「愿意联网」处理，
    与接口层「不带 `use_search` 即按开启处理」保持一致（第 7 组）。
    """
    req = SearchRequest(query="随便问点什么")

    assert req.query == "随便问点什么"
    assert req.urls == ()
    assert req.use_search is True
    assert req.has_urls is False

    # 默认（想搜）→ 会碰网络；明确不想搜且没链接 → 完全不该碰网络
    assert req.wants_external is True
    assert WITHOUT_URLS_SEARCH_OFF.wants_external is False, "没链接 + 不想搜 = 完全不该碰网络"

    assert WITH_URLS.has_urls is True
    assert WITH_URLS.wants_external is True, "链接必读，不受 use_search 约束（design D4）"
    assert WITHOUT_URLS_SEARCH_ON.wants_external is True


# ---------------------------------------------------------------- initial_step 三态
@pytest.mark.parametrize(
    ("req", "expected_name"),
    [
        (WITH_URLS, "读取你给的网页"),
        (WITHOUT_URLS_SEARCH_ON, "联网检索知识"),
        (WITHOUT_URLS_SEARCH_OFF, "理解你的输入"),
    ],
)
def test_three_states_when_provider_is_capable(req: SearchRequest, expected_name: str) -> None:
    """有能力联网的 Provider：三个名字分别对应「链接 / 想搜 / 都不」三态。"""
    step = build_initial_step(req, can_search_web=True, can_read_pages=True)

    assert step.name == expected_name
    assert step.detail, "每一步都要有给用户看的过程说明，不能是空串"


@pytest.mark.parametrize("req", [WITH_URLS, WITHOUT_URLS_SEARCH_ON, WITHOUT_URLS_SEARCH_OFF])
def test_noop_always_says_understand_input(req: SearchRequest) -> None:
    """没有联网能力的 Provider 永远说「理解你的输入」。

    这就是冲突点 14 的落点：**没有能力就不许显示「联网检索知识」**。
    显示能力的唯一后果是让用户以为在联网 —— 那正是本次要修的失败模式之一。
    """
    provider = NoopSearchProvider()

    assert provider.can_search_web is False
    assert provider.can_read_pages is False
    assert provider.initial_step(req).name == "理解你的输入"


def test_step_name_is_stable_across_gather() -> None:
    """名字回答「在做什么」，所以取材前后**必须一致**；结果由 detail 表达（冲突点 14）。

    旧实现里 `first_step()` 会在降级时把名字改回「理解你的输入」，
    于是「贴了链接但没读到」这件事既没有名字也没有详情能说明白。
    """
    provider = NoopSearchProvider()

    outcome = provider.gather(WITH_URLS)

    assert outcome.step_name == provider.initial_step(WITH_URLS).name
    assert outcome.first_step(concept_count=4).name == outcome.step_name


# ---------------------------------------------------------------- Noop 不发请求
def test_noop_gather_degrades_and_never_touches_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`gather()` 恒返回降级结果，且**不发出任何外部请求**。

    这条用「连 socket 都不许建立」来验，而不是只看返回值 ——
    只看返回值的话，一个偷偷联网但把结果丢掉的实现也能通过。
    """

    def _forbid(*args: object, **kwargs: object) -> None:
        raise AssertionError("NoopSearchProvider 不该建立任何网络连接")

    monkeypatch.setattr(socket.socket, "connect", _forbid)
    monkeypatch.setattr(socket, "create_connection", _forbid)

    provider = NoopSearchProvider()

    for request in (WITH_URLS, WITHOUT_URLS_SEARCH_ON, WITHOUT_URLS_SEARCH_OFF):
        outcome = provider.gather(request)
        assert outcome.degraded is True
        assert outcome.results == ()
        assert outcome.hit_count == 0
        assert outcome.provider == "none"
        assert outcome.end_reason == "disabled", "压根没打算联网，不是「试了没成」"
        assert outcome.rounds_used == 0


def test_noop_satisfies_protocol() -> None:
    """`NoopSearchProvider` 必须满足新协议（去掉 `step_name`、换成 `initial_step`）。"""
    provider = NoopSearchProvider()

    assert isinstance(provider, SearchProvider)
    assert not hasattr(provider, "step_name"), (
        "`step_name` 已废弃：第一步有三种名字，静态属性表达不了"
    )
    assert not hasattr(provider, "search"), "`search(query)` 已换成 `gather(request)`"


# ---------------------------------------------------------------- SearchResult / Outcome
def test_search_result_carries_kind_and_source() -> None:
    """每条资料要能区分「片段还是整页」「用户给的还是搜来的」。"""
    snippet = SearchResult(title="t", url="https://a.example", snippet="s")
    page = SearchResult(
        title="t",
        url="https://a.example",
        snippet="s",
        kind="page",
        source="user",
    )

    assert snippet.kind == "snippet"
    assert snippet.source == "web"
    assert page.kind == "page"
    assert page.source == "user"


def test_search_outcome_trace_defaults() -> None:
    """追溯字段的默认值（没跑循环的路径要能自然地表达「没跑」）。"""
    outcome = SearchOutcome(provider="none")

    assert outcome.rounds_used == 0
    assert outcome.tool_calls_used == 0
    assert outcome.end_reason == "disabled"
    assert outcome.limit_hit is None, "没触顶就没有上限名"


def test_limit_hit_is_the_end_reason_when_capped() -> None:
    """触顶时 `end_reason` 本身就含上限名，`limit_hit` 直接复用它。"""
    outcome = SearchOutcome(provider="tavily", end_reason="rounds_exhausted")

    assert outcome.limit_hit == "rounds_exhausted"
    assert SearchOutcome(provider="tavily", end_reason="done").limit_hit is None


def test_degraded_is_derived_from_results() -> None:
    """`degraded` 是派生值，不是一个能和 `results` 打架的独立字段。"""
    assert SearchOutcome(provider="tavily", results=()).degraded is True
    assert (
        SearchOutcome(
            provider="tavily",
            results=(SearchResult(title="t", url="https://a.example", snippet="s"),),
        ).degraded
        is False
    )


def test_first_step_reports_page_count_and_never_claims_zero_hits() -> None:
    """有资料时报条数（含整页数）；没资料时**不报「命中 0 条」**。"""
    outcome = SearchOutcome(
        provider="tavily",
        step_name="联网检索知识",
        results=(
            SearchResult(title="a", url="https://a.example", snippet="s"),
            SearchResult(title="b", url="https://b.example", snippet="s", kind="page"),
        ),
        end_reason="done",
    )

    step = outcome.first_step(concept_count=4)

    assert step.name == "联网检索知识"
    assert "2 条" in step.detail
    assert "整页 1 篇" in step.detail
    assert "0 条" not in step.detail


def test_first_step_says_so_when_external_access_failed() -> None:
    """去过外部但没取到 → 如实说「未取到可用资料」，而不是假装只是「理解输入」。"""
    never_tried = SearchOutcome(provider="none", end_reason="disabled")
    tried_failed = SearchOutcome(provider="tavily", end_reason="done")

    assert "核心概念" in never_tried.first_step(concept_count=5).detail
    assert "未取到" in tried_failed.first_step(concept_count=5).detail


# ---------------------------------------------------------------- 注入上限
def test_reference_caps_defaults_match_settings() -> None:
    """`ReferenceCaps` 的兜底默认值必须与 `Settings` 的默认值一致。

    两处默认值是**同一个事实**：写岔了就会出现「单测里截断成 600、线上截断成别的」，
    而且不会报错，只表现为 Prompt 忽大忽小。
    """
    s = Settings(_env_file=None)
    caps = ReferenceCaps()

    assert caps.snippet_max_chars == s.search_snippet_max_chars
    assert caps.page_max_chars == s.search_page_max_chars
    assert caps.total_max_chars == s.search_reference_max_chars


def test_reference_caps_from_settings() -> None:
    """`from_settings` 是取值的唯一入口（采集器与 Prompt 注入共用同一份）。"""
    s = Settings(_env_file=None)
    caps = ReferenceCaps.from_settings(s)

    assert caps.snippet_max_chars == s.search_snippet_max_chars
    assert caps.page_max_chars == s.search_page_max_chars
    assert caps.total_max_chars == s.search_reference_max_chars
    # 条数上限是**结构性**兜底（真实约束是字符总量），因此不跟 search_max_results 绑定 ——
    # 后者是「一次 search 要几条」，与「一共注入几条」不是同一件事。
    assert caps.max_items >= s.search_max_results


def test_reference_caps_limit_for_kind() -> None:
    """整页与片段各用各的上限。"""
    caps = ReferenceCaps()

    assert caps.limit_for("page") == caps.page_max_chars
    assert caps.limit_for("snippet") == caps.snippet_max_chars


def test_as_reference_respects_total_char_cap() -> None:
    """字符总量上限是真正的护栏：条数少也可能体积巨大（单页可达 7 万字符）。"""
    caps = ReferenceCaps(snippet_max_chars=100, page_max_chars=100, total_max_chars=200)
    outcome = SearchOutcome(
        provider="tavily",
        results=tuple(
            SearchResult(title=f"t{i}", url=f"https://{i}.example", snippet="x" * 90)
            for i in range(5)
        ),
    )

    text = outcome.as_reference(caps=caps)

    assert text, "至少要给出第一条"
    assert len(text) <= caps.total_max_chars + 200, "总量上限之外只允许拼接开销"
    assert text.count("来源：") < 5, "不该把所有条目都塞进去"
