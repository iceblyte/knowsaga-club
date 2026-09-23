"""链接抽取的单测（`add-web-search-grounding` 第 7 组）。

## 这些用例为什么值得单独一个文件

它们定义的是**服务端与前端必须达成一致的那条规则**：大厅那只 pill 显示「读取你给的网页」
还是「基于已有知识出题」，取决于前端按同一组正则算出来的结果；而真正去读哪些页面
取决于服务端算出来的结果。两边算得不一样的表现是：

  pill 说「会读取你的链接」，进度条第一步却说「理解你的输入」—— 用户只会认为功能坏了。

所以每个用例都是「两边都必须同意」的判据，而不只是后端的实现细节。

## 与前端的一致性怎么保证

不靠人眼比对。判据落在 `shared/link-cases.json`，本文件的下方用例把它当**唯一真源**
逐条跑一遍；前端的对应检查是 `frontend/scripts/check_links_parity.mjs`
（做法与 `shared/scoring-cases.json` / `check_scoring_parity.mjs` 完全相同）。
**改抽取规则要先改那份共享用例。**

上面那些手写用例仍然保留：它们解释「为什么这条规则长这样」，
而共享用例只保证「两端算得一样」—— 两边一起错的话只有这里拦得住。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.utils.links import extract_urls, has_url

#: 仓根下的 `shared/link-cases.json`（本文件在 `backend/tests/` 下）。
_LINK_CASES_PATH = Path(__file__).resolve().parents[2] / "shared" / "link-cases.json"


def _shared_cases() -> list[dict[str, object]]:
    payload = json.loads(_LINK_CASES_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


def test_shared_case_file_is_not_empty() -> None:
    """共享用例必须真的存在且非空 —— 空文件会让下面那条参数化用例「全绿」。"""
    cases = _shared_cases()
    assert len(cases) >= 20, f"共享用例太少（{len(cases)} 条），文件可能被误删"


@pytest.mark.parametrize("case", _shared_cases(), ids=lambda case: str(case["name"]))
def test_matches_shared_cases(case: dict[str, object]) -> None:
    """前端与后端的共同判据（`shared/link-cases.json`）。"""
    text = str(case["text"])
    expected = tuple(str(item) for item in case["urls"])  # type: ignore[union-attr]
    assert extract_urls(text) == expected
    assert has_url(text) is bool(expected)


def test_plain_url_is_extracted() -> None:
    """一个纯链接。"""
    assert extract_urls("https://a.example/x") == ("https://a.example/x",)


def test_url_with_surrounding_text() -> None:
    """链接 + 说明文字：说明文字不进结果。"""
    assert extract_urls("帮我按这个页面出题：https://a.example/x 谢谢") == ("https://a.example/x",)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("中文句号结尾 https://a.example/p。后面还有字", "https://a.example/p"),
        ("括号里（https://a.example/p）", "https://a.example/p"),
        ("逗号后面 https://a.example/p, 还有", "https://a.example/p"),
        ("英文句号 https://a.example/p. And more", "https://a.example/p"),
        ("问号是查询串 https://a.example/p?q=1", "https://a.example/p?q=1"),
    ],
)
def test_trailing_punctuation_is_stripped(text: str, expected: str) -> None:
    """粘在链接后面的标点要剥掉。

    不剥的话得到的是一个访问不了的地址，Tavily 会回 `{"error": ...}`，
    表现为「取材静默降级」—— 用户贴了链接却说没读到。
    """
    assert extract_urls(text) == (expected,)


def test_multiple_urls_keep_order_and_dedupe() -> None:
    """多个链接：保序（决定题目引用资料的编号顺序）且去重。"""
    text = "https://b.example 和 https://a.example 以及 https://b.example 再来一次"

    assert extract_urls(text) == ("https://b.example", "https://a.example")


def test_www_form_gets_a_scheme() -> None:
    """`www.` 形态补 `https://`：Tavily 的 extract 只接受带 scheme 的 URL。

    这不算「猜测式补全」—— `www.` 开头本身就是「这是一个网址」的声明。
    """
    assert extract_urls("看看 www.a.example/docs") == ("https://www.a.example/docs",)


def test_www_form_is_deduped_against_its_schemed_twin() -> None:
    """同一个地址的两种写法只留一个（先出现的那种形态胜出）。"""
    assert extract_urls("www.a.example 与 https://www.a.example") == ("https://www.a.example",)


@pytest.mark.parametrize(
    "text",
    [
        "example.com/docs",  # 裸域名：可能是句中的举例，不猜
        "a.example",  # 同上
        "什么是以 RAG 为核心的检索增强生成",
        "ftp://a.example/x",  # 只认 http(s)
        "mailto:someone@example.com",
        "见第 3 章 https 协议的说明",  # 只有「https」三个字母，不是链接
        "",
    ],
)
def test_looks_like_a_link_but_is_not(text: str) -> None:
    """看起来像链接但不算：**不猜**。

    `example.com` 这种形态在一句话里太常见（可能就是域名举例）。
    猜错的表现是「模型跑去读一个用户没打算给的页面」，而用户根本不会察觉 ——
    比「没识别出来」更糟（后者用户会再说一遍）。
    """
    assert extract_urls(text) == ()
    assert has_url(text) is False


def test_https_and_http_are_both_kept() -> None:
    """`http://` 也认（内网或老站点常见），不擅自升级成 https。"""
    assert extract_urls("http://a.example/x") == ("http://a.example/x",)


def test_case_insensitive_scheme() -> None:
    """`HTTPS://` 也认（大小写不该让链接消失）。"""
    assert extract_urls("HTTPS://A.example/X") == ("HTTPS://A.example/X",)


def test_url_with_chinese_and_percent_encoding_survives() -> None:
    """中文路径与百分号编码都不能被吃掉。"""
    url = "https://a.example/%E4%B8%AD%E6%96%87/页面"

    assert extract_urls(f"读这个 {url}") == (url,)


def test_has_url_matches_extract_urls() -> None:
    """`has_url` 就是 `bool(extract_urls(...))` —— 不许是另一套判断。"""
    for text in ("https://a.example", "www.a.example", "example.com", "没有链接"):
        assert has_url(text) is bool(extract_urls(text))


def test_none_like_input_is_tolerated() -> None:
    """空输入返回空元组（参数上不允许 None，但空串必须优雅处理）。"""
    assert extract_urls("   ") == ()
