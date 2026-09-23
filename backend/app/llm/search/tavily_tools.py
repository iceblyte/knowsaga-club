"""官方 `langchain-tavily` 两个工具的装配层。

## 这一层只做一件事：把**实例级参数**按本次请求装好

上游 `TavilySearch._run` / `TavilyExtract._run` 里有 `forbidden_params` 机制：
`country`、`max_results`、`format` 这类参数**只能在构造实例时设**，调用时传会直接抛
`ValueError`。所以「动态调整结果条数 / 动态调整城市范围」这两个诉求**只能落在这里**，
不可能交给模型（design D2）。

| 谁决定 | 参数 |
|---|---|
| **服务端（本模块）** | `country`（按输入语种）、`max_results`（按配置）、`search_depth`（**钉死 `basic`**，见下）、所有 `include_*` 布尔开关、`format` |
| **模型（调用时）** | `query`、`topic`、`time_range`、`start_date`/`end_date`、`include_domains`/`exclude_domains`；extract 侧的 `urls`、`extract_depth`、`query` |

## 四个刻意的选择

1. **不打开 `include_raw_content`。** 它是实例级开关，一旦打开就**无条件**给每条搜索结果
   附整页正文（实测单页可达 7.5 万字符），必然挤爆 `quiz_max_tokens=4096`，
   而且不可按需。用 `tavily_extract` 是同一需求的**按需**版本，还多一个 `query` 能聚焦。
2. **`handle_tool_error=False`。** 上游默认 `True`，会把「0 命中」抛出的 `ToolException`
   转成一段**字符串**返回 —— 那东西长得像正常返回，采集器很容易把它当正文。
   关掉之后 0 命中以异常抛出，由取材循环自己捕获，语义不再有歧义（design D6 第 2 条）。
3. **每次请求重新装工具，不做模块级缓存。** 缓存会把上一个用户的语种偏好带给下一个用户，
   症状是「英文问题搜出一堆中文站」，极难归因。
4. **`search_depth` 也钉在实例上（`basic`）。** 原因不是省钱，而是**能不能搜到**：

   2026-09-22 端到端实测（`docs/MVP开发计划.md` §12.4），模型把深度选成了 `fast`，
   Tavily 的回答是 **400**：

       Country parameter is not supported for fast or ultra-fast search_depth.

   我们为了「中文输入偏向中文来源」固定传了 `country`，于是「模型随手选个深度」
   就能把整次检索打成失败 —— 那一次 4 个调用额度全撞在同一个 400 上，
   最终 `search_state='degraded'`，用户贴的链接一条都没读到。

   钉住它是**根治**而不是绕过：上游 `TavilySearch._run` 里写的是

       search_depth=self.search_depth if self.search_depth else search_depth

   实例级的值优先于调用级的值，所以模型就算传了也压不过这一行。
   想拿长正文的正确姿势是 `tavily_extract` 读那一页（Prompt 第三节已这么教，
   这条替代路径必须留，否则模型会试图用深度来达到「要更多正文」的目的）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.exceptions import AppError, ErrorCode
from app.utils.lang import looks_chinese

if TYPE_CHECKING:  # pragma: no cover - 只为类型标注，运行期不 import 上游包
    from langchain_tavily import TavilyExtract, TavilySearch

    from app.core.config import Settings
    from app.llm.search.base import SearchRequest

#: extract 每页取几段。上游默认 3 —— 会在正文里插分段标记，取 1 拿完整正文更省事。
EXTRACT_CHUNKS_PER_SOURCE = 1


def _pick_country(request: SearchRequest, settings: Settings) -> str | None:
    """按输入语种选地区偏好。

    `None` 是合法取值 = 不施加地区偏好（部署方可以把两个配置都设成 `None` 完全关掉）。
    """
    if looks_chinese(request.query):
        return settings.search_country_default
    return settings.search_country_default_en


def require_tavily_key(settings: Settings) -> str:
    """取出并校验 Tavily 的 key，未配置就抛 5000（design D13）。

    **这必须是唯一一份校验与文案。** 两处都写一份的话，总有一处先漂移，
    而症状是「报文里说的是 A，日志里说的是 B」。

    Args:
        settings: 配置来源。

    Raises:
        AppError(5000): 未配置 `TAVILY_API_KEY`。
            它算**配置错误**而不是「降级」：这时的表现是「开关显示开着、配置写着开着，
            实际一次都没联网」—— 是最难发现的一类谎报。
    """
    api_key = (settings.tavily_api_key or "").strip()
    if not api_key:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "已开启联网检索但未配置 TAVILY_API_KEY，请在 .env 里填写后重启服务",
            detail="tavily_api_key is empty",
        )
    return api_key


def build_tavily_tools(
    request: SearchRequest, settings: Settings
) -> tuple[TavilySearch, TavilyExtract]:
    """构造本次请求专用的两个工具实例。

    Args:
        request: 本次取材请求（决定语种与条数）。
        settings: 配置来源（key、条数、地区偏好）。

    Raises:
        AppError: 未配置 `TAVILY_API_KEY`。**这里必须自己拦** —— 上游是在**构造期**
            由 `validate_environment` 抛 pydantic 的英文消息，形状随版本变，
            而我们要给的是「配置错了、错在哪」这句话（见 design D13）。
    """
    # 延迟 import：`langchain_tavily` 只在真的要用真实检索时才需要，
    # 不该让「开关没开」的部署也跟着加载它。
    from langchain_tavily import TavilyExtract, TavilySearch
    from langchain_tavily._utilities import (
        TavilyExtractAPIWrapper,
        TavilySearchAPIWrapper,
    )

    # ⚠️ 变量名刻意**不叫 `api_key`**：`tools/scan_secrets.py` 的「写死密钥」规则
    # 只看 `api_key=` 后面那一串标识符，会把 `api_key = 函数调用()` 误判成硬编码密钥。
    # 给安全规则开口子比换个更准的名字危险得多，所以改名字（`tavily_key` 也更准确 ——
    # 它是 Tavily 的 key，与下面 `tavily_api_key=` 的实参同名）。
    tavily_key = require_tavily_key(settings)

    search_kwargs: dict[str, Any] = {
        # 显式把 key 交给 APIWrapper：不依赖构造期的环境变量回退（与项目 Settings 注入风格一致）
        "api_wrapper": TavilySearchAPIWrapper(tavily_api_key=tavily_key),
        "max_results": settings.search_max_results,
        "country": _pick_country(request, settings),
        # ⚠️ 必须钉死 `basic`（模块 docstring 第 4 条）：`fast` / `ultra-fast` 与 `country`
        # 互斥，模型一旦选了就是 400；`advanced` 则是 2 倍计费。两者都不要。
        "search_depth": "basic",
        # 以下全部保持关闭：它们要么会无条件放大体积，要么会抬高失败率或计费
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_image_descriptions": False,
        "include_favicon": False,
        "include_usage": False,
        "auto_parameters": False,
        "exact_match": False,
        # 见模块 docstring 第 2 条
        "handle_tool_error": False,
        "name": "tavily_search",
        "description": (
            "关键词联网检索。用于获取你训练数据覆盖不到的**新**知识（新概念、新版本、"
            "近期事件、特定产品的官方说明）。输入是一个检索词串。"
        ),
    }
    search = TavilySearch(**search_kwargs)

    extract = TavilyExtract(
        # ⚠️ 上游这个字段名是 `apiwrapper`（没有下划线），`TavilySearch` 才叫 `api_wrapper`
        apiwrapper=TavilyExtractAPIWrapper(tavily_api_key=tavily_key),
        extract_depth="basic",
        format="markdown",
        chunks_per_source=EXTRACT_CHUNKS_PER_SOURCE,
        include_images=False,
        include_favicon=False,
        include_usage=False,
        handle_tool_error=False,
        name="tavily_extract",
        description=(
            "按网址读取整个网页的正文。当用户给出了具体链接、或某条检索结果看起来是"
            "权威原文（官方文档、规范、发布说明）而你需要完整内容时使用。输入是一个网址列表。"
        ),
    )
    return search, extract
