"""取材结果的采集与清洗（`add-web-search-grounding` 第 5 组）。

## 为什么这一层的测试要照抄上游的「返回形态」

第 0 组在真实 key 下实测出**三种返回形态**，其中两种长得像"成功的工具返回"：

| 形态 | 含义 | 不显式处理会怎样 |
|---|---|---|
| `dict` 含 `error` 键（值是**异常对象**） | HTTP 非 200 / 参数被拦 | 把报错当命中，报错文本进 Prompt |
| `str` | 0 命中（`ToolException` 被 `handle_tool_error` 转成文本） | 把错误提示当正文 |
| `dict` 含 `results` | 真命中 | —— |

所以本文件里的每一份 fixture 都按实测形状手工构造（**不含任何第三方网页正文**，
13.3 要求被跟踪文件里不出现真实抓取内容）。

## 与任务书的一处说明

`tasks.md` 5.1 ⑦ 把「总量超上限被截断」放在采集器里。实际的总量上限作用在
`as_reference()`（`base.py`，第 2 组已交付并有单测）。本条因此落成
「采集器只管单条上限 + 组装时总量上限仍然生效」的联动断言 ——
把总量再在采集器里实现一遍会变成**两个事实**，那正是 design D6 明确要避免的。
"""

from __future__ import annotations

import logging

import pytest

from app.llm.search.base import ReferenceCaps, SearchRequest, SearchResult
from app.llm.search.collector import ToolOutput, clean_text, collect_results

CAPS = ReferenceCaps(snippet_max_chars=120, page_max_chars=300, total_max_chars=400)

USER_URL = "https://user.example/page"
WEB_URL = "https://web.example/post"

REQUEST_PLAIN = SearchRequest(query="Harness Engineering")
REQUEST_WITH_URL = SearchRequest(query=f"按这个页面出题 {USER_URL}", urls=(USER_URL,))


def _search_payload(*items: dict) -> dict:
    """实测形状：`{query, results:[{title,url,content,score,raw_content}], response_time}`。"""
    return {"query": "q", "results": list(items), "response_time": 1.23}


def _extract_payload(*items: dict) -> dict:
    """实测形状：`{results:[{url,title,raw_content,images}], failed_results, request_id}`。"""
    return {"results": list(items), "failed_results": [], "request_id": "abc"}


# ---------------------------------------------------------------- ① search 映射
def test_search_results_are_mapped_to_snippets() -> None:
    """search 命中 → `SearchResult(kind="snippet", source=...)`。"""
    output = ToolOutput(
        tool="tavily_search",
        payload=_search_payload(
            {"title": "示例文章 A", "url": WEB_URL, "content": "正文片段", "score": 0.87}
        ),
    )

    results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert len(results) == 1
    item = results[0]
    assert item.title == "示例文章 A"
    assert item.url == WEB_URL
    assert item.snippet == "正文片段"
    assert item.kind == "snippet"
    assert item.source == "web"


def test_search_hit_on_user_url_is_marked_as_user_source() -> None:
    """「来源」看的是 URL 属于谁，而不是「谁发起的调用」。

    用户贴了链接、模型又恰好搜到同一个 URL 时，这条资料仍应算用户给的 ——
    否则「我贴的链接被读了吗」这个问题在 `references` 里就查不出来了（design D9）。
    """
    output = ToolOutput(
        tool="tavily_search",
        payload=_search_payload({"title": "t", "url": USER_URL, "content": "片段"}),
    )

    results = collect_results([output], request=REQUEST_WITH_URL, caps=CAPS)

    assert results[0].source == "user"


# ---------------------------------------------------------------- ② extract 映射
def test_extract_results_are_mapped_to_pages() -> None:
    """extract 命中 → `kind="page"`，正文取自 `raw_content`。"""
    output = ToolOutput(
        tool="tavily_extract",
        payload=_extract_payload(
            {"title": "示例页面", "url": WEB_URL, "raw_content": "# 标题\n\n正文内容"}
        ),
    )

    results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert len(results) == 1
    assert results[0].kind == "page"
    assert results[0].title == "示例页面"
    assert "正文内容" in results[0].snippet


def test_extract_title_falls_back_to_markdown_heading() -> None:
    """标题链第 ② 级：没有 `title` 时取 `raw_content` 里第一个 markdown 标题行。"""
    output = ToolOutput(
        tool="tavily_extract",
        payload=_extract_payload(
            {"title": "", "url": WEB_URL, "raw_content": "前言\n\n## 真正的标题\n\n正文"}
        ),
    )

    title = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)[0].title

    assert title == "真正的标题", "markdown 标记（#）要剥掉，只留标题文字"


def test_extract_title_falls_back_to_host() -> None:
    """标题链第 ③ 级：既没 `title` 也没标题行 → 用 URL 的 host。"""
    output = ToolOutput(
        tool="tavily_extract",
        payload=_extract_payload({"title": None, "url": "https://sub.web.example/post", "raw_content": "无标题正文"}),
    )

    title = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)[0].title

    assert title == "sub.web.example"


def test_extract_title_is_empty_rather_than_invented() -> None:
    """标题链第 ④ 级：连 host 都取不到 → 空字符串。**绝不编造标题。**"""
    output = ToolOutput(
        tool="tavily_extract",
        payload=_extract_payload({"title": "", "url": "", "raw_content": "无标题正文"}),
    )

    results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert results == () or results[0].title == ""


# ---------------------------------------------------------------- ③ error 形态
def test_error_payload_is_not_a_hit_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """含 `error` 键的返回是**失败的调用**，但它长得像正常返回 —— 必须显式判掉。"""
    output = ToolOutput(
        tool="tavily_search",
        payload={"error": ValueError("Unauthorized: missing api key")},
    )

    with caplog.at_level(logging.WARNING):
        results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert results == ()
    assert any("Unauthorized" in r.getMessage() for r in caplog.records), (
        "失败原因要进日志，否则线上只能看到「这次没资料」而不知道为什么"
    )


# ---------------------------------------------------------------- ④ 0 命中 / 调用失败
def test_string_payload_is_treated_as_no_result() -> None:
    """`str` 形态 = 0 命中（`handle_tool_error=True` 时的形态），整段当无结果，不解析。"""
    output = ToolOutput(
        tool="tavily_search",
        payload="No search results found for 'qzx'. You can try again with a more specific query.",
    )

    assert collect_results([output], request=REQUEST_PLAIN, caps=CAPS) == ()


def test_tool_exception_is_not_a_hit() -> None:
    """`handle_tool_error=False` 时 0 命中会抛异常 —— 同样不算命中。"""
    output = ToolOutput(tool="tavily_extract", ok=False, error="ToolException: No extracted results found")

    assert collect_results([output], request=REQUEST_PLAIN, caps=CAPS) == ()


# ---------------------------------------------------------------- ⑤ 清洗上游省略标记
def test_omission_markers_are_cleaned() -> None:
    """`[...]` 是上游的省略符（实测形态），`<chunk n>` 是防御性形态 —— 两者都不许进 Prompt。"""
    assert "[...]" not in clean_text("前半句 [...] 后半句")
    assert "<chunk" not in clean_text("<chunk 1> 第一段 <chunk 2> 第二段")
    assert "chunk" not in clean_text("<chunk 1> 第一段 <chunk 2> 第二段")


def test_cleaning_keeps_markdown_links_intact() -> None:
    """`[...](url)` 是合法的 markdown 链接文本，不能把它也当成省略符清掉。"""
    assert clean_text("[...](https://a.example)") == "[...](https://a.example)"


def test_cleaning_collapses_double_spaces_left_behind() -> None:
    """清掉省略符会留下双空格；不收拾会一路进 Prompt。"""
    assert "  " not in clean_text("前半句 [...] 后半句")


def test_cleaning_does_not_destroy_other_brackets() -> None:
    """只动省略符，别把正常方括号（引用编号等）也吃掉。"""
    assert clean_text("见 [1] 与 [2]") == "见 [1] 与 [2]"


# ---------------------------------------------------------------- ⑥ 去重
def test_same_url_keeps_the_more_complete_page() -> None:
    """同一 URL 先 search 命中、后 extract 整页 → 只留一条，且是整页那条。"""
    outputs = [
        ToolOutput(tool="tavily_search", payload=_search_payload({"title": "t", "url": WEB_URL, "content": "片段"})),
        ToolOutput(
            tool="tavily_extract",
            payload=_extract_payload({"title": "T", "url": WEB_URL, "raw_content": "整页正文"}),
        ),
    ]

    results = collect_results(outputs, request=REQUEST_PLAIN, caps=CAPS)

    assert len(results) == 1
    assert results[0].kind == "page"
    assert "整页正文" in results[0].snippet


def test_dedup_keeps_first_position() -> None:
    """去重后保序：先出现的 URL 仍排在前面（否则题解里的资料顺序会莫名跳动）。"""
    outputs = [
        ToolOutput(
            tool="tavily_search",
            payload=_search_payload(
                {"title": "a", "url": "https://a.example", "content": "片段 a"},
                {"title": "b", "url": "https://b.example", "content": "片段 b"},
            ),
        ),
        ToolOutput(
            tool="tavily_extract",
            payload=_extract_payload({"title": "A", "url": "https://a.example", "raw_content": "整页 a"}),
        ),
    ]

    results = collect_results(outputs, request=REQUEST_PLAIN, caps=CAPS)

    assert [r.url for r in results] == ["https://a.example", "https://b.example"]


# ---------------------------------------------------------------- ⑦ 截断
def test_snippet_is_truncated_with_an_explicit_marker() -> None:
    """单条片段超上限被截断，并留下显式标记（静默截断会让模型脑补结尾）。"""
    output = ToolOutput(
        tool="tavily_search",
        payload=_search_payload({"title": "t", "url": WEB_URL, "content": "字" * 500}),
    )

    snippet = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)[0].snippet

    assert len(snippet) < 500
    assert "截断" in snippet


def test_page_is_truncated_by_its_own_cap() -> None:
    """整页有自己的上限（实测单页可达 7.5 万字符，一次就能挤爆 Prompt，design D14）。"""
    caps = ReferenceCaps(snippet_max_chars=100, page_max_chars=200, total_max_chars=4000)
    output = ToolOutput(
        tool="tavily_extract",
        payload=_extract_payload({"title": "t", "url": WEB_URL, "raw_content": "字" * 5000}),
    )

    snippet = collect_results([output], request=REQUEST_PLAIN, caps=caps)[0].snippet

    assert len(snippet) < 400, "整页必须按 page_max_chars（200）截，不是按 snippet 的 100"
    assert "截断" in snippet


def test_total_cap_still_holds_when_assembling_reference() -> None:
    """总量上限作用在组装阶段（`as_reference`），本组只保证两者用的是同一组常量。"""
    caps = ReferenceCaps(snippet_max_chars=200, page_max_chars=200, total_max_chars=300)
    outputs = [
        ToolOutput(
            tool="tavily_search",
            payload=_search_payload(
                *[
                    {"title": f"t{i}", "url": f"https://{i}.example", "content": "字" * 190}
                    for i in range(5)
                ]
            ),
        )
    ]

    results = collect_results(outputs, request=REQUEST_PLAIN, caps=caps)
    from app.llm.search.base import SearchOutcome

    text = SearchOutcome(provider="tavily", results=results).as_reference(caps=caps)

    assert len(results) == 5, "采集阶段不替组装阶段做取舍"
    assert text.count("来源：") < 5, "组装阶段必须按字符总量砍掉多余的条目"


# ---------------------------------------------------------------- ⑧ 未知形状
@pytest.mark.parametrize(
    "payload",
    [
        {},  # 缺 results 键
        {"results": "not-a-list"},  # results 不是列表
        {"results": [None, 123]},  # 列表里不是 dict
        {"results": [{"content": "没有 url"}]},  # 条目缺 url
        None,  # 空返回
    ],
)
def test_unknown_shapes_only_warn(payload: object, caplog: pytest.LogCaptureFixture) -> None:
    """上游改版时只记 warning 并跳过，**不抛异常** —— 取材失败不该拖垮出题。"""
    output = ToolOutput(tool="tavily_search", payload=payload)

    with caplog.at_level(logging.WARNING):
        results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert results == ()


def test_unknown_tool_name_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """不认识的名字（上游加了新工具）只警告，不猜它的形状。"""
    output = ToolOutput(tool="tavily_map", payload={"results": [{"url": "x"}]})

    with caplog.at_level(logging.WARNING):
        results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert results == ()


def test_empty_input_collects_to_empty_tuple() -> None:
    """一次调用都没有（开关关、或循环一轮都没跑）→ 空元组，不是 None。"""
    assert collect_results([], request=REQUEST_PLAIN, caps=CAPS) == ()


def test_result_shape_is_immutable_dataclass() -> None:
    """采集产物就是 `base.SearchResult`，不另造一种结构（否则两处会各演化一套）。"""
    output = ToolOutput(
        tool="tavily_search",
        payload=_search_payload({"title": "t", "url": WEB_URL, "content": "片段"}),
    )

    assert isinstance(collect_results([output], request=REQUEST_PLAIN, caps=CAPS)[0], SearchResult)
