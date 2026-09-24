"""`kb_search`：交给取材 Agent 的**第三个工具**（design D1）。

## 它的位置

| 文件 | 职责 |
|---|---|
| `llm/kb/store.py` | 向量库里怎么存、怎么带隔离地取（唯一的过滤实现点） |
| `services/kb_service.py` | 「谁的库」「能不能检索」「失败怎么说」（`search_base` / `search_for_tool`） |
| **本文件** | 把上面那两层的产物**翻译成一次工具调用的形状**：参数、返回值、给模型看的描述 |

三层分开是为了让「隔离」只有一处实现。本文件**不碰** Chroma，也不拼任何
`where` 条件 —— 它拿到 `KbChunk` 之后只做字段映射（`KbChunk` → `SearchResult` 的原料）。

## 为什么失败返回错误体而不是抛异常

`tavily_*` 是上游包，我们改不了它的错误形态，只能在自己的循环里捕获（`agent._invoke_tool`）。
`kb_search` 是我们自己写的工具，没有理由沿用那个形态：

- 返回 `{"error": ...}` 走的是 `collector` **已经认得**的那条路
  （`collector.collect_results()` 里 `"error" in payload` → 判定为调用失败并记日志）；
- 抛异常要多走一层捕获，而且模型**看不到**失败原因 —— 错误体会被
  `agent._render_for_model()` 原样回喂给它，于是它知道「这次没查到」，
  而不是觉得自己已经拿到了资料、继续瞎编。

## 描述文案是给模型看的，不是给用户看的

模型只能按描述判断该不该调这个工具。所以描述里必须出现两件它必须知道的事：
**这是用户自己上传的材料**，以及**范围只有这一个库**。少了第一件，它会把
知识库片段当成网上随便搜来的东西，遇到与训练数据冲突时会倾向于推翻它。
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.search.base import KB_TOOL_NAME, KB_URL_PREFIX, SearchRequest, kb_url

logger = get_logger(__name__)

#: 给模型看的描述。要点见模块 docstring。
KB_TOOL_DESCRIPTION = (
    "在**用户自己上传的资料库**里检索相关内容。它搜的不是互联网，"
    "范围严格限定在这次指定的那一个资料库里。当用户提到「我的资料」「我上传的文档」"
    "「这份讲义」，或者学习主题正是这些材料的内容时使用。输入是一个检索词串。"
)

#: 空库 / 没命中时给模型的说明。**必须区分这两者**（spec 要求系统能区分
#: 「库是空的」与「检索没命中」）：前者该建议用户先上传，后者该换个说法再试。
_NOTE_EMPTY_BASE = "这个资料库目前还没有可检索的内容（文档可能仍在解析中或解析失败）。"
_NOTE_NO_HIT = "在你的资料库里没有找到与这次检索相关的内容。"


def build_kb_tool(request: SearchRequest, settings: Settings) -> Any | None:
    """按本次请求造一个 `kb_search` 工具；请求里没有库时返回 `None`。

    Args:
        request: 取材请求。`request.kb` 为 `None` 时**不建工具** ——
            工具一旦绑给模型它就会去调，而这时库里没有本次要用的资料，
            用户会拿到一份莫名其妙的题。
        settings: 配置（条数上限、向量库目录、向量化凭据）。

    Returns:
        `StructuredTool`，或 `None`。
    """
    scope = request.kb
    if scope is None:
        return None

    # 惰性 import：`kb_service` 会拉起仓库层与 `langchain_core.embeddings`，
    # 而 KB 关着的部署连 `llm/kb/` 都不该加载（见 `llm/kb/__init__.py`）。
    from langchain_core.tools import StructuredTool

    def kb_search(query: str) -> dict[str, Any]:
        """查用户自己的资料库。"""
        return search_knowledge_base(
            user_id=scope.user_id, kb_id=scope.kb_id, query=query, settings=settings
        )

    return StructuredTool.from_function(
        func=kb_search,
        name=KB_TOOL_NAME,
        description=KB_TOOL_DESCRIPTION,
    )


def search_knowledge_base(
    *, user_id: int, kb_id: int, query: str, settings: Settings
) -> dict[str, Any]:
    """检索并把结果翻成工具的返回形状。

    返回形状（与 `tavily_search` 同构 —— 采集器与 Prompt 的编号都按它工作）::

        {"query": "...", "results": [{"title", "url", "content",
                                      "source", "kind", "filename", "chunk_index"}]}

    没命中时 `results` 为空列表，并附一句 `note` 说明**为什么**空；
    检索失败时返回 `{"error": "..."}`（见模块 docstring）。

    **本函数不抛异常。**
    """
    from app.services import kb_service

    try:
        outcome = kb_service.search_for_tool(
            user_id=int(user_id), kb_id=int(kb_id), query=query, settings=settings
        )
    except Exception as exc:  # noqa: BLE001 - 见模块 docstring：失败要能被模型看见
        logger.exception("知识库检索工具抛出异常：user=%s kb=%s", user_id, kb_id)
        return {"query": query, "error": f"知识库检索失败：{type(exc).__name__}"}

    if outcome.reason == kb_service.KB_SEARCH_FAILED:
        # `search_base` 已经把细节写进日志了，这里给模型一句话就够 ——
        # 上游报文进 Prompt 既帮不了它，又可能带出内部信息。
        logger.warning("知识库检索判定为失败：user=%s kb=%s", user_id, kb_id)
        return {"query": query, "error": "知识库检索失败，本次没有可用资料"}

    if not outcome.chunks:
        note = (
            _NOTE_EMPTY_BASE
            if outcome.reason == kb_service.KB_SEARCH_EMPTY_BASE
            else _NOTE_NO_HIT
        )
        return {"query": query, "results": [], "note": note}

    return {
        "query": query,
        "results": [_as_result(chunk) for chunk in outcome.chunks],
    }


def _as_result(chunk: Any) -> dict[str, Any]:
    """一条片段 → 工具返回里的一项。

    - `url` 用伪 URL（design D6）：片段没有网址，而采集器按 url 去重，
      所以同一文档的不同片段必须有不同的 url。
    - `title` 用**文件名**：`as_reference()` 靠它渲染「你的知识库《X》」。
    - `content` 与 `tavily_search` 的 `content` 同名，因为它们的含义一样
      （一段可截断的正文）。截断统一由 `collector` 按 `snippet_max_chars` 做 ——
      这里不截，避免同一件事有两个上限。
    """
    return {
        "title": chunk.filename,
        "url": kb_url(kb_id=chunk.kb_id, doc_id=chunk.doc_id, chunk_index=chunk.chunk_index),
        "content": chunk.text,
        "source": "kb",
        "kind": "snippet",
        "filename": chunk.filename,
        "chunk_index": int(chunk.chunk_index),
    }


__all__ = [
    "KB_TOOL_DESCRIPTION",
    "KB_TOOL_NAME",
    "KB_URL_PREFIX",
    "build_kb_tool",
    "search_knowledge_base",
]
