"""官方 Tavily 工具的装配（`add-web-search-grounding` 第 3 组）。

**全部 mock、不联网**：这里只验「实例级参数是不是按我们说的那套装上去的」，
真正的调用行为由第 11 组的端到端验证覆盖。

为什么值得钉死：上游 `TavilySearch._run` / `TavilyExtract._run` 里有 `forbidden_params`
机制，把 `country` / `max_results` / `format` 这类参数限制成**只能实例化时设**。
一旦我们把它们放到调用时传，上游直接抛 `ValueError` —— 而那是运行期才炸，
所以必须在装配这一层就用断言锁住（design D2）。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import AppError
from app.llm.search.base import SearchRequest
from app.llm.search.tavily_tools import build_tavily_tools

ZH_QUERY = "具身智能的世界模型最新进展"
EN_QUERY = "what is harness engineering"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "tavily_api_key": "tvly-unit-test-key",
        "search_max_results": 5,
        "search_country_default": "china",
        "search_country_default_en": None,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


# ---------------------------------------------------------------- key 前置校验
def test_missing_key_raises_before_upstream_validation() -> None:
    """没配 key 时由**我们的工厂**抛错，而不是让上游在构造期抛 ValidationError。

    上游的报错是英文的 pydantic 消息（而且形状会随版本变），
    这里要的是「配置错了、错在哪」这句话 —— 见 design D13：key 为空算配置错误，不是降级。
    """
    settings = _settings(tavily_api_key="")

    with pytest.raises(AppError) as excinfo:
        build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)

    assert "TAVILY_API_KEY" in str(excinfo.value)


# ---------------------------------------------------------------- country 判定
def test_country_from_query_language() -> None:
    """中文输入走 `search_country_default`，英文输入走 `search_country_default_en`。"""
    settings = _settings(search_country_default="china", search_country_default_en="united states")

    zh_search, _ = build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)
    en_search, _ = build_tavily_tools(SearchRequest(query=EN_QUERY), settings)

    assert zh_search.country == "china"
    assert en_search.country == "united states"


def test_country_can_be_disabled_entirely() -> None:
    """两处配置都是 `None` 时必须装出 `country=None`（不传地区偏好）。"""
    settings = _settings(search_country_default=None, search_country_default_en=None)

    zh_search, _ = build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)
    en_search, _ = build_tavily_tools(SearchRequest(query=EN_QUERY), settings)

    assert zh_search.country is None
    assert en_search.country is None


# ---------------------------------------------------------------- 实例级参数
def test_instance_level_params_come_from_settings_not_the_model() -> None:
    """`max_results` 与那几个布尔开关一律由服务端决定。"""
    settings = _settings(search_max_results=7)

    search, _ = build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)

    assert search.max_results == 7, "条数是实例级参数，模型改不了"
    assert search.include_answer is False
    assert search.include_raw_content is False, (
        "一旦打开就无条件给每条结果附整页正文，必挤爆 quiz_max_tokens"
    )
    assert search.include_images is False
    assert search.auto_parameters is False, "打开会让上游偷偷把 search_depth 提到 advanced（2 倍计费）"
    assert search.exact_match is False, "打开会要求 query 必须带引号短语，会让 0 命中率飙升"


def test_extract_tool_is_configured_for_markdown_pages() -> None:
    """extract 侧：markdown 格式、有 `chunks_per_source`、图片与用量都不带。"""
    settings = _settings()

    _, extract = build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)

    assert extract.format == "markdown", "正文要 markdown，标题行才好提取"
    assert extract.chunks_per_source, "必须有值 —— 上游默认 3 会在正文里插分段标记"
    assert extract.include_images is False
    assert extract.include_usage is False
    assert extract.include_favicon is False


def test_tool_names_are_the_official_ones() -> None:
    """模型看到的工具名必须是官方的两个名字，别自己改名。"""
    settings = _settings()

    search, extract = build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)

    assert search.name == "tavily_search"
    assert extract.name == "tavily_extract"


def test_tools_are_rebuilt_per_request_not_shared() -> None:
    """连续两次不同语种的请求必须拿到不同的 `country`。

    实例级参数每次请求重装、**不做模块级缓存** —— 缓存会把上一个用户的语种偏好
    带给下一个用户，而症状是「英文问题搜出一堆中文站」，极难归因。
    """
    settings = _settings(search_country_default="china", search_country_default_en="united states")

    first, _ = build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)
    second, _ = build_tavily_tools(SearchRequest(query=EN_QUERY), settings)

    assert first is not second
    assert first.country != second.country


def test_tool_errors_are_not_swallowed() -> None:
    """`handle_tool_error=False`：0 命中必须以异常抛出，而不是变成一段字符串返回。

    上游默认是 `True`，会把 `ToolException` 转成一段给模型看的错误文本 ——
    那东西长得像正常返回，采集器很容易把它当正文（design D6 第 2 条）。
    """
    settings = _settings()

    search, extract = build_tavily_tools(SearchRequest(query=ZH_QUERY), settings)

    assert search.handle_tool_error is False
    assert extract.handle_tool_error is False


# ---------------------------------------------------------------- 语种判定
def test_looks_chinese_handles_mixed_input() -> None:
    """中英混排是真实场景（「什么是 Harness Engineering」），不能判成纯英文。

    阈值定得低是有意的：判成中文的代价只是多一个倾向，判成英文的代价是
    中文用户拿回一堆他读不了的英文资料。
    """
    from app.utils.lang import cjk_ratio, looks_chinese

    assert looks_chinese(ZH_QUERY) is True
    assert looks_chinese(EN_QUERY) is False
    assert looks_chinese("什么是 Harness Engineering") is True
    assert looks_chinese("") is False, "空串不该崩，也不该算中文"
    assert cjk_ratio("abc123") == 0.0
    assert cjk_ratio("汉字") == 1.0
    assert cjk_ratio("") == 0.0, "没有中英文字符时分母为 0，不能除零"
