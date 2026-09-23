"""把上游工具的返回，采集并清洗成 `base.SearchResult`。

## 为什么这一层必须存在

`langchain-tavily` 的工具返回值有**三种形态**，而且其中两种长得像"成功了"
（第 0 组在真实 key 下实测确认，见 design D6）。如果调用方直接 `payload["results"]`：

| 实测形态 | 真实含义 | 不处理会怎样 |
|---|---|---|
| `{"error": <异常对象>}` | HTTP 非 200 / 参数被拦 | `KeyError` 或把报错当命中 |
| `str`（一段错误提示文本） | 0 命中 | 把「没搜到」的提示语当成正文塞进 Prompt |
| `{"results": [...]}` | 真命中 | 正常路径 |

所以这里**只做三件事**：判形态、翻译字段、清洗标记。**不做取舍**（去重与截断以外
的所有取舍都在组装阶段）—— 采集不替组装做决定，否则同一个上限会在两处各写一遍。

## 与 `handle_tool_error` 的关系

`tavily_tools.py` 把 `handle_tool_error` 显式设成了 `False`，于是 0 命中会**抛异常**
而不是返回 `str`。这里仍然处理 `str` 形态：上游改默认值是**静默**的，
而静默漂移的后果是「错误提示被当成资料」，正是本次要修的失败模式之一。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.llm.search.base import (
    ReferenceCaps,
    SearchRequest,
    SearchResult,
    truncate,
)

logger = get_logger(__name__)

#: 上游的省略符。实测形态是字面 `[...]`（出现在句子中间）。
#: 负向断言 `(?!\()` 是为了放过 markdown 链接文本 `[...](url)` —— 那是合法内容，不是省略符。
_OMISSION = re.compile(r"\[\.\.\.\](?!\()")

#: 防御性形态：上游 `chunks_per_source > 1` 时的分段标记（实测默认值下没出现）。
_CHUNK = re.compile(r"<chunk\s*\d+\s*>", re.IGNORECASE)

#: 清洗后留下的连续空白（省略符被替换成空格会留下双空格）。
_SPACES = re.compile(r"[ \t]{2,}")

#: 已知的两个工具名。不认识的名字只警告 —— 上游加了新工具时，猜它的形状更危险。
_SEARCH_TOOL = "tavily_search"
_EXTRACT_TOOL = "tavily_extract"
_KNOWN_TOOLS = frozenset({_SEARCH_TOOL, _EXTRACT_TOOL})


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """一次工具调用的原始产出。

    保留 `ok` 与 `error` 而不是只留 `payload`：超时与异常在 `agent.py` 里就被拦下了，
    没有 `payload` 可留，但**失败原因必须留下来**（否则线上只能看到「这次没资料」）。

    Attributes:
        tool: 工具名。
        payload: 上游返回原样（`dict` / `str` / `None`）；调用失败时是 `None`。
        ok: 调用有没有抛异常 / 超时。
        error: `ok=False` 时的诊断文本。
    """

    tool: str
    payload: object = None
    ok: bool = True
    error: str = ""


def clean_text(text: str) -> str:
    """清掉上游的省略/分段标记，并收拾留下的空白。

    为什么不静默截断式地删掉省略符：`[...]` 表示「这里被上游省略了」，
    保留一个空格能让句子不粘连（`foo[...]bar` → `foobar` 会直接改变词形）。
    """
    if not text:
        return ""
    cleaned = _CHUNK.sub(" ", text)
    cleaned = _OMISSION.sub(" ", cleaned)
    cleaned = _SPACES.sub(" ", cleaned)
    return cleaned.strip()


def _first_heading(raw: str) -> str:
    """取 `raw_content` 里第一个 markdown 标题行的**文字**（剥掉 `#`）。"""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _title_for(item: dict, url: str, raw: str) -> str:
    """标题取值链（四级，design D6 第 3 条）。

    `title` → markdown 标题行 → URL 的 host → 空字符串。
    最后一级是空串而**不是** URL 本身或「未命名网页」之类：不编造标题。
    """
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    heading = _first_heading(raw)
    if heading:
        return heading
    return urlparse(url).netloc if url else ""


def _source_for(url: str, request: SearchRequest) -> str:
    """这条资料算谁的。

    判据是 **URL 在不在用户的输入里**，不是「哪次调用取回来的」——
    用户贴了链接、模型又恰好搜到同一个 URL 时，它仍要能被认出来（design D9）。
    """
    return "user" if url in request.urls else "web"


def _pick_items(payload: dict, tool: str) -> list[dict] | None:
    """取出 `results` 列表；形状不对就返回 `None`（由调用方记警告）。"""
    results = payload.get("results")
    if not isinstance(results, list):
        logger.warning("取材返回缺少可用的 results 列表，已跳过：tool=%s keys=%s", tool, list(payload))
        return None
    return [item for item in results if isinstance(item, dict)]


def _collect_search(payload: dict, request: SearchRequest, caps: ReferenceCaps) -> list[SearchResult]:
    items = _pick_items(payload, _SEARCH_TOOL)
    if items is None:
        return []
    out: list[SearchResult] = []
    for item in items:
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        out.append(
            SearchResult(
                title=(item.get("title") or "").strip() if isinstance(item.get("title"), str) else "",
                url=url,
                snippet=truncate(clean_text(item.get("content") or ""), caps.snippet_max_chars),
                kind="snippet",
                source=_source_for(url, request),
            )
        )
    return out


def _collect_extract(payload: dict, request: SearchRequest, caps: ReferenceCaps) -> list[SearchResult]:
    items = _pick_items(payload, _EXTRACT_TOOL)
    if items is None:
        return []
    out: list[SearchResult] = []
    for item in items:
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        raw = item.get("raw_content") or ""
        if not isinstance(raw, str):
            raw = ""
        out.append(
            SearchResult(
                title=_title_for(item, url, raw),
                url=url,
                snippet=truncate(clean_text(raw), caps.page_max_chars),
                kind="page",
                source=_source_for(url, request),
            )
        )
    return out


def _completeness(item: SearchResult) -> tuple[int, int]:
    """「更完整」的判据：先看是不是整页，再看长度。

    整页一定比片段完整（片段是上游摘要的摘要），同形态之间再比长度。
    """
    return (1 if item.kind == "page" else 0, len(item.snippet))


def _dedupe(items: Sequence[SearchResult]) -> list[SearchResult]:
    """按 URL 去重，**保留更完整的那条**，并保持首次出现的顺序。

    保序的理由：资料顺序会随 `as_reference()` 进 Prompt 并决定 `[1] [2]` 的编号，
    顺序忽然跳动的表现是「同一份资料昨天排第 1、今天排第 3」——排查时会被当成 bug。
    """
    picked: dict[str, SearchResult] = {}
    order: list[str] = []
    for item in items:
        existing = picked.get(item.url)
        if existing is None:
            picked[item.url] = item
            order.append(item.url)
            continue
        if _completeness(item) > _completeness(existing):
            picked[item.url] = item
    return [picked[url] for url in order]


def collect_results(
    outputs: Sequence[ToolOutput],
    *,
    request: SearchRequest,
    caps: ReferenceCaps,
) -> tuple[SearchResult, ...]:
    """把若干次工具调用的产出，采集并清洗成资料列表。

    Args:
        outputs: 按发生顺序排列的工具产出。
        request: 本次取材请求（决定「这条资料算谁的」）。
        caps: 单条截断上限。**必须与组装阶段用同一组常量**（design D6）。

    Returns:
        去重后的资料元组；一条都没取到时是空元组（不是 `None`）。

    **不抛异常**：任何无法理解的返回都只记日志并跳过 ——
    取材是出题的增强项，不该把出题任务拖垮（design D13）。
    """
    collected: list[SearchResult] = []

    for output in outputs:
        if not output.ok:
            logger.warning("取材调用失败，已跳过：tool=%s reason=%s", output.tool, output.error)
            continue

        payload = output.payload

        if payload is None:
            logger.warning("取材返回为空，已跳过：tool=%s", output.tool)
            continue
        if isinstance(payload, str):
            # 0 命中（`handle_tool_error=True` 时的形态）。整段不解析 —— 里面是给模型看的建议。
            logger.debug("取材无结果（字符串形态，通常是 0 命中）：tool=%s", output.tool)
            continue
        if not isinstance(payload, dict):
            logger.warning(
                "取材返回形状无法识别，已跳过：tool=%s type=%s", output.tool, type(payload).__name__
            )
            continue
        if "error" in payload:
            # ⚠️ 这是「调用失败」，但它长得像一次成功的返回（design D6 第 1 条）。
            logger.warning("取材返回携带 error，判定为调用失败：tool=%s error=%r", output.tool, payload["error"])
            continue

        if output.tool not in _KNOWN_TOOLS:
            logger.warning("未知的取材工具返回，已跳过：tool=%s", output.tool)
            continue

        if output.tool == _SEARCH_TOOL:
            collected.extend(_collect_search(payload, request, caps))
        else:
            collected.extend(_collect_extract(payload, request, caps))

    return tuple(_dedupe(collected))


def serialize_references(
    results: Sequence[SearchResult], *, caps: ReferenceCaps
) -> list[dict[str, str]]:
    """把资料压成能进 `quizzes.references` 的 JSON 结构。

    每条只留五项：`title` / `url` / `snippet` / `kind` / `source`。**不留整页正文** ——
    实测单页可达 74,801 字符，整篇存进去会让这张表迅速膨胀，而它本来就不是资料的
    权威副本（权威副本在原始网页上）。

    ⚠️ `truncate` 是**幂等**的（`text[:limit] + 标记`，对已经截断过的文本再跑一次结果不变），
    所以这里再截一遍不会产生两个「已截断」标记 —— 这一层是防御，
    真正的截断发生在 `collect_results()`，两处共用同一组 `caps`（design D6）。
    """
    return [
        {
            "title": item.title,
            "url": item.url,
            "snippet": truncate(item.snippet, caps.limit_for(item.kind)),
            "kind": item.kind,
            "source": item.source,
        }
        for item in results
    ]
