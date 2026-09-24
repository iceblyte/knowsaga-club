"""采集器认不认识知识库片段的返回（`add-private-knowledge-base` 第 8 组）。

## 为什么单独一个文件，而不是塞进 `test_search_collector.py`

那份文件是**已交付并被看护**的（`add-web-search-grounding` 第 5 组），它钉的是
「上游三种返回形态」这一组事实。本次新增的是**我们自己的第四种形态**
（`kb_search` 的返回），两者来源不同、判据不同 —— 分开之后，
「上游改版导致采集器失准」与「我们自己新增了一种来源」这两类失败不会互相掩盖。

## 本组要守住的三件事

1. **伪 URL 认得出 kb**：`collector._source_for()` 必须把 `kb://...` 判成 `source="kb"`
   —— 判不出来它就会落到 `"web"`，而那个错误的后果是知识库片段在 Prompt 里
   被当成「网上搜来的东西」（design D5/D6）。
2. **白名单**：没登记进 `_KNOWN_TOOLS` 的工具名只会记一条 warning 并跳过。
   这条**必须是回归用例** —— 症状是「命中数恒为 0，日志只说这次没资料」，
   而不报错。已有一次先例（`add-web-search-grounding` 期间新工具名漏登记）。
3. **知识库片段与网页片段互不干扰**：两种来源同时出现时各归各的，
   去重仍按 URL（伪 URL 之间、以及伪 URL 与真实 URL 之间都不会撞）。
"""

from __future__ import annotations

import logging

import pytest

from app.llm.search.base import KB_URL_PREFIX, ReferenceCaps, SearchRequest
from app.llm.search.collector import ToolOutput, collect_results
from app.llm.kb.tools import KB_TOOL_NAME

CAPS = ReferenceCaps(snippet_max_chars=120, page_max_chars=300, total_max_chars=4000)

WEB_URL = "https://web.example/post"
KB_URL_A = f"{KB_URL_PREFIX}7/12#0"
KB_URL_B = f"{KB_URL_PREFIX}7/12#1"

REQUEST_PLAIN = SearchRequest(query="Harness Engineering")


def _kb_payload(*items: dict) -> dict:
    """`kb_search` 的返回形状（由 `llm/kb/tools.py` 决定，见 `test_kb_tool.py`）。"""
    return {"query": "监督学习", "results": list(items)}


def _kb_item(url: str = KB_URL_A, content: str = "监督学习是从标注数据中学习映射函数。") -> dict:
    return {
        "title": "机器学习讲义.md",
        "url": url,
        "content": content,
        "source": "kb",
        "kind": "snippet",
        "filename": "机器学习讲义.md",
        "chunk_index": 0,
    }


# ---------------------------------------------------------------- ① 映射
def test_kb_results_are_collected_as_snippets() -> None:
    """知识库片段被采进来，且 `source` 是 `kb`。"""
    output = ToolOutput(tool=KB_TOOL_NAME, payload=_kb_payload(_kb_item()))

    results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert len(results) == 1
    item = results[0]
    assert item.source == "kb"
    assert item.kind == "snippet"
    assert item.title == "机器学习讲义.md"
    assert item.url == KB_URL_A
    assert "监督学习" in item.snippet


def test_kb_title_never_comes_from_the_pseudo_url() -> None:
    """伪 URL **不许**被当成标题来源（网页那条链会取 URL 的 host）。

    知识库片段的标题是文件名，是工具直接给的事实。如果走了网页那条标题链，
    `urlparse("kb://7/12#0").netloc` 会得到 `7`，于是 Prompt 里出现
    「你的知识库《7》」这种令人费解的东西。
    """
    output = ToolOutput(tool=KB_TOOL_NAME, payload=_kb_payload({**_kb_item(), "title": ""}))

    title = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)[0].title

    assert title in ("", "机器学习讲义.md"), title
    assert title != "7", "标题不许从伪 URL 的 host 里编出来"


# ---------------------------------------------------------------- ② 白名单（回归）
def test_unregistered_tool_name_yields_no_hits(caplog: pytest.LogCaptureFixture) -> None:
    """⚠️ **回归用例**：工具名没登记进 `_KNOWN_TOOLS` ⇒ 命中数为 0。

    这条不是在测 `collector` 有多笨，而是在给「新增一个取材工具」这个动作
    立一个显式的检查点：漏登记不报错、不抛异常，只是**安静地一条都采不到**，
    而日志里那句 warning 是全链路唯一的线索。已有一先例
    （`add-web-search-grounding` 期间），所以它必须被钉住。
    """
    output = ToolOutput(tool="kb_search_v2", payload=_kb_payload(_kb_item()))

    with caplog.at_level(logging.WARNING):
        results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert results == ()
    assert any("kb_search_v2" in r.getMessage() for r in caplog.records), (
        "未知工具名必须留下含名字的 warning，否则这条路径完全不可观测"
    )


def test_kb_tool_name_is_registered() -> None:
    """正向的那一面：`KB_TOOL_NAME` 确实在白名单里。

    与上一条配对 —— 一条证明「没登记会静默失败」，一条证明「现在登记了」。
    只有前一条的话，把名字删掉它照样通过。
    """
    output = ToolOutput(tool=KB_TOOL_NAME, payload=_kb_payload(_kb_item()))

    assert len(collect_results([output], request=REQUEST_PLAIN, caps=CAPS)) == 1


# ---------------------------------------------------------------- ③ 两种来源共存
def test_web_and_kb_results_coexist() -> None:
    """一次取材里两种来源同时出现 → 各归各的，顺序按调用发生的先后。"""
    outputs = [
        ToolOutput(
            tool="tavily_search",
            payload={"query": "q", "results": [{"title": "示例文章", "url": WEB_URL, "content": "网页片段"}]},
        ),
        ToolOutput(tool=KB_TOOL_NAME, payload=_kb_payload(_kb_item())),
    ]

    results = collect_results(outputs, request=REQUEST_PLAIN, caps=CAPS)

    assert [item.source for item in results] == ["web", "kb"]
    assert [item.url for item in results] == [WEB_URL, KB_URL_A]


def test_two_chunks_of_one_document_are_not_deduped() -> None:
    """同一文档的两个片段**各有各的伪 URL**，所以去重不会把它们合成一条。

    这是伪 URL 里那个 `#{chunk_index}` 存在的全部理由 —— 用文件名当 url
    的话，一份 50 段的文档在 Prompt 里只会剩一段。
    """
    output = ToolOutput(
        tool=KB_TOOL_NAME,
        payload=_kb_payload(
            _kb_item(KB_URL_A, "第一段的正文内容。"),
            _kb_item(KB_URL_B, "第二段的正文内容。"),
        ),
    )

    results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert len(results) == 2
    assert {item.url for item in results} == {KB_URL_A, KB_URL_B}


def test_kb_url_is_never_marked_as_user_or_web() -> None:
    """`_source_for()` 认伪 URL —— 判不出来就会落到默认的 `"web"`。

    这一条与上一条的区别：上一条看的是**采到几条**，这一条看的是**归谁**。
    """
    # 故意把同一个伪 URL 也塞进 request.urls：即使这样，它也必须算 `kb`
    request = SearchRequest(query=f"查资料 {KB_URL_A}", urls=(KB_URL_A,))
    output = ToolOutput(tool=KB_TOOL_NAME, payload=_kb_payload(_kb_item()))

    results = collect_results([output], request=request, caps=CAPS)

    assert results[0].source == "kb", "伪 URL 必须优先判成 kb，不能被「在输入里出现过」抢走"


# ---------------------------------------------------------------- ④ 失败 / 空
def test_kb_error_payload_is_not_a_hit(caplog: pytest.LogCaptureFixture) -> None:
    """`kb_search` 的失败形态是错误体（不抛异常），采集器必须判成「没有资料」。"""
    output = ToolOutput(tool=KB_TOOL_NAME, payload={"query": "x", "error": "知识库检索失败"})

    with caplog.at_level(logging.WARNING):
        results = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)

    assert results == ()
    assert any("知识库检索失败" in r.getMessage() for r in caplog.records)


def test_kb_note_only_payload_is_not_a_hit() -> None:
    """空库 / 没命中时返回的是 `{"results": [], "note": ...}` → 空元组，不是 `None`。"""
    output = ToolOutput(tool=KB_TOOL_NAME, payload={"query": "x", "results": [], "note": "库是空的"})

    assert collect_results([output], request=REQUEST_PLAIN, caps=CAPS) == ()


def test_kb_text_is_not_scrubbed_of_upstream_markers() -> None:
    """⚠️ 知识库正文**不做** `clean_text()` 清洗。

    清洗清的是上游网页的省略符 `[...]` 与分段标记 `<chunk 1>`。
    知识库正文是**用户自己写的文字** —— 里面出现同样的字符是合法内容，
    对它跑一遍清洗会把用户原文静默改掉（没有日志），用户看到的是
    「我明明写了这段」。所以 kb 这条分支只截断，不清洗。
    """
    text = "见 [...] 与 <chunk 1> 这两个符号都是我自己写的。"
    output = ToolOutput(tool=KB_TOOL_NAME, payload=_kb_payload(_kb_item(content=text)))

    snippet = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)[0].snippet

    assert snippet == text, "用户自己的正文必须原样保留"


def test_kb_snippet_is_truncated_by_the_snippet_cap() -> None:
    """知识库片段按 `snippet_max_chars` 截断（与网页片段同一个上限）。

    单条上限是**共享**的（spec 要求的是「知识库条数上限独立于网页」，
    那是 `kb_search_top_k`，在检索侧）。这里刻意不另开一个上限：
    两类片段都是「一段摘要」，共用一个数是对的；条数才是形态差异所在。
    """
    output = ToolOutput(tool=KB_TOOL_NAME, payload=_kb_payload(_kb_item(content="字" * 500)))

    snippet = collect_results([output], request=REQUEST_PLAIN, caps=CAPS)[0].snippet

    assert len(snippet) < 500
    assert "截断" in snippet
