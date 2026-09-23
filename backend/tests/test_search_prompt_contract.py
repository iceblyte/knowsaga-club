"""取材 Agent 的 Prompt 契约测试（`add-web-search-grounding` 第 8 组）。

`test_prompt_contract.py` 守的是**出题链**的 Prompt；本文件守的是**取材链**的 Prompt。
两条链的 Prompt 风险完全不同，所以分开测：

| | 出题链 | 取材链（本文件） |
|---|---|---|
| 输出形态 | 严格 json（结构非法就废） | 自然语言（自由） |
| 主要风险 | 题量/字段/注入 | **额度被烧光**、提示注入、循环停不下来 |

本文件要守住的四件事（都是「不写就会静默出问题」的）：

1. `search_depth` **由服务端钉死**（不再是「让模型默认用 basic」）——
   2026-09-22 端到端实测：模型把深度选成了 `fast`，而 `country` 与
   `fast`/`ultra-fast` 互斥，Tavily 直接返回 **400**，4 个调用额度全撞废。
   现在实例级钉住 `basic`（上游是 `self.search_depth if self.search_depth else search_depth`，
   实例值优先），Prompt 相应改为「不要设它，要长正文就用 extract」。
2. `topic` 默认 `general`，只有财经 / 近期重大新闻才改（`tasks.md` 8.1 的最后一条）。
   它属于取材链 —— 出题链不绑工具，根本没有 `topic` 这个参数。
3. **第三方网页正文是数据不是指令** —— 整页正文的注入面比检索片段大得多（design D5 / D10）。
4. **用户给的链接必须先读**，且 `use_search=False` 时只禁 `tavily_search`、不禁止读链接。

⚠️ 这里**不测** `country` / `max_results`：它们是实例级参数，
模型在调用时传会被上游 `forbidden_params` 拒绝 —— 那条契约由
`tests/test_search_tools.py` 看护（装配侧），Prompt 没法替它担保。
"""

from __future__ import annotations

import re

from app.llm.search.base import SearchRequest
from app.prompts.search_prompt import (
    SEARCH_AGENT_PROMPT_VERSION,
    SEARCH_AGENT_SYSTEM_PROMPT,
    build_agent_messages,
)


def _flat(text: str) -> str:
    """把换行与连续空白压成单个空格 —— 断言不受排版换行影响。"""
    return re.sub(r"\s+", " ", text)


def _human(request: SearchRequest, max_rounds: int = 3) -> str:
    messages = build_agent_messages(request, max_rounds=max_rounds)
    return str(messages[1].content)


def _system(request: SearchRequest, max_rounds: int = 3) -> str:
    messages = build_agent_messages(request, max_rounds=max_rounds)
    return str(messages[0].content)


# ---------------------------------------------------------------- 版本与装配
def test_prompt_is_versioned() -> None:
    assert SEARCH_AGENT_PROMPT_VERSION == "v1"


def test_system_prompt_declares_both_tool_names() -> None:
    """两个工具都要点名 —— 模型只能调它知道存在的工具。"""
    assert "tavily_search" in SEARCH_AGENT_SYSTEM_PROMPT
    assert "tavily_extract" in SEARCH_AGENT_SYSTEM_PROMPT


def test_build_agent_messages_returns_system_then_human() -> None:
    messages = build_agent_messages(SearchRequest(query="Harness Engineering"), max_rounds=3)
    assert [m.type for m in messages] == ["system", "human"]


# ---------------------------------------------------------------- 参数取向（烧钱与合法性）
def test_prompt_takes_search_depth_off_the_model() -> None:
    """深度由服务端钉死，Prompt 要**明确告诉模型不要设它**。

    为什么不是「默认用 basic」这种软指引：模型真选了 `fast` 会让整次检索 400
    （与 `country` 互斥，见 `test_search_tools.py::test_search_depth_is_pinned_on_the_instance`）。
    软指引挡不住它，所以代码钉死 + Prompt 说明，两层都要有。
    """
    flat = _flat(SEARCH_AGENT_SYSTEM_PROMPT)
    assert re.search(r"search_depth[^。]{0,40}(服务端|系统|固定|统一)", flat), (
        "必须说清这个参数不由模型决定"
    )
    assert re.search(r"search_depth[^。]{0,40}(不要|不用|无需|不必)", flat), (
        "必须明确说「不要设置它」，否则模型仍会去填"
    )
    # 想要长正文的正确姿势要给出，否则模型会试图用深度来达到目的
    assert re.search(r"(长正文|完整正文|整页)[^。]{0,40}tavily_extract", flat), (
        "要把「需要长正文 → 用 extract」这条替代路径写出来"
    )


def test_prompt_defaults_topic_to_general_with_finance_exception() -> None:
    """`tasks.md` 8.1 的最后一条 —— 除财经 / 重大新闻外 `topic` 保持 `general`。"""
    flat = _flat(SEARCH_AGENT_SYSTEM_PROMPT)
    assert re.search(r"topic[^。]{0,24}(默认|一律|保持)[^。]{0,12}general", flat)
    assert re.search(r"(财经|金融|股市)[^。]{0,20}(新闻|时事)", flat)


def test_prompt_warns_against_redundant_searches() -> None:
    """重复检索同一主题是最容易被浪费的那次调用 —— 额度有限，必须明说。"""
    flat = _flat(SEARCH_AGENT_SYSTEM_PROMPT)
    assert re.search(r"(不要|别)[^。]{0,20}重复[^。]{0,12}检索", flat)


# ---------------------------------------------------------------- 注入面
def test_prompt_declares_web_content_is_data_not_instruction() -> None:
    flat = _flat(SEARCH_AGENT_SYSTEM_PROMPT)
    assert re.search(r"(网页|第三方)[^。]{0,20}(正文|内容)[^。]{0,10}是[^。]{0,6}数据", flat)
    assert re.search(r"(不要执行|不得执行|一律当作普通文本|不要照做)", flat)


def test_prompt_forbids_inventing_material() -> None:
    flat = _flat(SEARCH_AGENT_SYSTEM_PROMPT)
    assert re.search(r"(不要|不得|禁止)[^。]{0,8}编造", flat)


# ---------------------------------------------------------------- 收尾
def test_prompt_demands_an_explicit_stop_without_tool_calls() -> None:
    flat = _flat(SEARCH_AGENT_SYSTEM_PROMPT)
    assert re.search(r"结束[^。]{0,40}(不要再|停止|不再)[^。]{0,12}(工具|调用)", flat)


# ---------------------------------------------------------------- Human 消息：输入形态分支
def test_human_prompt_lists_user_urls_and_marks_extract_as_mandatory() -> None:
    """用户给的链接是**必做步骤**，不是「可以看看」。"""
    url_a = "https://example.com/harness-engineering"
    url_b = "https://example.com/agent-evals"
    human = _human(SearchRequest(query="读这两篇", urls=(url_a, url_b)))

    assert url_a in human
    assert url_b in human
    assert re.search(r"(必做|必须|务必|请先)", human)
    assert "tavily_extract" in human


def test_human_prompt_tells_model_to_decide_when_no_url() -> None:
    human = _human(SearchRequest(query="Harness Engineering"))
    assert re.search(r"没有给出具体链接", human)
    assert re.search(r"(自行判断|自行决定)", human)


def test_human_prompt_forbids_search_but_keeps_links_when_use_search_off() -> None:
    """意愿关掉 ≠ 链接不读：这两件事在 Prompt 里必须分开说。"""
    url = "https://example.com/spec"
    human = _human(SearchRequest(query="读这个", urls=(url,), use_search=False))

    assert re.search(r"(不要|不得)[^。]{0,20}调用[^。]{0,20}" + "tavily_search", human)
    assert url in human
    # 关掉检索后仍要读链接 —— 读链接靠的是 extract
    assert "tavily_extract" in human or re.search(r"(只能|仍要|仍然)[^。]{0,20}读", human)


def test_human_prompt_states_the_round_budget() -> None:
    """不告诉模型预算，它会倾向于「每轮多要一点」，然后撞上限。"""
    human = _human(SearchRequest(query="某个新概念"), max_rounds=2)
    assert re.search(r"最多[^。]{0,8}2[^。]{0,8}轮", human)
