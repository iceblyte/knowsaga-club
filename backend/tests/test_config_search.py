"""联网检索的配置项契约（`add-web-search-grounding` 第 1 组）。

为什么值得单独一个测试文件：这些数值直接决定取材的**时延上界**与**注入 Prompt 的体积上界**。
写错一个的表现是「模型答非所问」（Prompt 被资料挤爆）或「出题任务卡死」（单次调用无超时），
**两种都不报错** —— 所以必须被断言钉住，而不是靠评审看一眼。

数值来源见 `openspec/changes/add-web-search-grounding/design.md` 的 D2 / D12 / D14，
以及 `docs/MVP开发计划.md` §12.3 的第 0 组实测（单页 `raw_content` 实测可达 74,801 字符）。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def _defaults() -> Settings:
    """只读代码里的默认值。

    `_env_file=None` 断掉仓库根 `.env`：本文件的字段都不在 `conftest.TEST_ENV` 里，
    不断掉就会被开发者本地配置污染（环境变量仍然生效，与项目既有做法一致）。
    """
    return Settings(_env_file=None)


# ---------------------------------------------------------------- 默认值
def test_search_limits_have_expected_defaults() -> None:
    """三个硬上限 + 三个截断上限的默认值。"""
    s = _defaults()

    # 取材的硬上限（D5）：没有它们，一次慢工具调用就能把出题预算吃光
    assert s.search_agent_max_rounds == 3
    assert s.search_agent_max_tool_calls == 4
    assert s.search_agent_budget_seconds == 20

    # 单次工具调用的超时（D12）：上游 `requests.post` **没有** timeout，必须我们外包
    assert s.search_tool_timeout_seconds == 8

    # extract 单独一个更长的超时（2026-09-22 端到端实测追加，见 §12.4）：
    # 一次 `tavily_extract` 取回的是 **整页正文**（实测 2.2 万–7.5 万字符），
    # 把它和「返回一小段 JSON」的 search 用同一个 8s 上限，会让「用户贴的链接读不到」
    # —— 而那正是本产品最不能失败的一条路径（design D4）。
    assert s.search_extract_timeout_seconds > s.search_tool_timeout_seconds

    # 每次 search 的结果条数（实例级参数，由服务端决定，不让模型改）
    assert s.search_max_results == 5

    # 截断上限（D14）：整页正文实测可达 7.5 万字符，而 quiz_max_tokens 只有 4096
    assert s.search_snippet_max_chars > 0
    assert s.search_page_max_chars > s.search_snippet_max_chars
    assert s.search_reference_max_chars > s.search_page_max_chars

    # 三者必须远小于 quiz_max_tokens 能容纳的量级，否则资料会把 Prompt 挤爆
    assert s.search_reference_max_chars <= 40_000
    assert s.quiz_max_tokens == 4096


def test_search_country_defaults() -> None:
    """`country` 的地域偏好默认值（D3）。"""
    s = _defaults()

    assert s.search_country_default == "china"
    assert s.search_country_default_en is None


# ---------------------------------------------------------------- 可被环境变量覆盖
@pytest.mark.parametrize(
    ("env_key", "env_value", "attr", "expected"),
    [
        ("SEARCH_AGENT_MAX_ROUNDS", "5", "search_agent_max_rounds", 5),
        ("SEARCH_AGENT_MAX_TOOL_CALLS", "7", "search_agent_max_tool_calls", 7),
        ("SEARCH_AGENT_BUDGET_SECONDS", "33", "search_agent_budget_seconds", 33),
        ("SEARCH_TOOL_TIMEOUT_SECONDS", "12", "search_tool_timeout_seconds", 12),
        ("SEARCH_EXTRACT_TIMEOUT_SECONDS", "21", "search_extract_timeout_seconds", 21),
        ("SEARCH_MAX_RESULTS", "9", "search_max_results", 9),
        ("SEARCH_SNIPPET_MAX_CHARS", "321", "search_snippet_max_chars", 321),
        ("SEARCH_PAGE_MAX_CHARS", "4321", "search_page_max_chars", 4321),
        ("SEARCH_REFERENCE_MAX_CHARS", "8000", "search_reference_max_chars", 8000),
    ],
)
def test_search_limits_can_be_overridden_by_env(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    env_value: str,
    attr: str,
    expected: int,
) -> None:
    """部署方要能按自己的额度与耐心调整这些上限。"""
    from app.core.config import get_settings

    monkeypatch.setenv(env_key, env_value)
    get_settings.cache_clear()
    try:
        assert getattr(get_settings(), attr) == expected
    finally:
        get_settings.cache_clear()


def test_search_country_can_be_disabled_by_empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SEARCH_COUNTRY_DEFAULT=` 必须解析成 `None`（= 完全关掉地区偏好）。

    ⚠️ 这条不写就会踩坑：pydantic 对 `str | None` 会把空字符串校验成 `""`，
    于是 `country=""` 被传给上游 —— 既不报错、也不生效，只表现为「地区偏好神秘失效」。
    """
    from app.core.config import get_settings

    monkeypatch.setenv("SEARCH_COUNTRY_DEFAULT", "")
    monkeypatch.setenv("SEARCH_COUNTRY_DEFAULT_EN", "")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.search_country_default is None
        assert s.search_country_default_en is None
    finally:
        get_settings.cache_clear()


def test_search_country_can_be_set_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """反过来，显式给值就要拿到那个值。"""
    from app.core.config import get_settings

    monkeypatch.setenv("SEARCH_COUNTRY_DEFAULT", "united states")
    monkeypatch.setenv("SEARCH_COUNTRY_DEFAULT_EN", "united kingdom")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.search_country_default == "united states"
        assert s.search_country_default_en == "united kingdom"
    finally:
        get_settings.cache_clear()
