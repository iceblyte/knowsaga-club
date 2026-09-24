"""向量化：百炼（DashScope）`text-embedding-v4`。

## 为什么用原生 SDK 而不是 OpenAI 兼容端点

`TextEmbedding.call` 有一个 `text_type` 参数（`document` / `query`），
官方的用法是**入库的文本传 `document`、检索的查询传 `query`**。
OpenAI 兼容端点没有这个概念（OpenAI 的 embeddings 接口里不存在对应字段），
走兼容端点等于把这个区分丢掉 —— 而它恰好是影响召回质量的那一项。

实测（本机安装了 dashscope 1.27.7 后直接读的源码）：
`TextEmbedding.call(model, input, workspace=None, api_key=None, text_type=None,
dimension=None, output_type=None, instruct=None, **kwargs)`，
v4 支持的维度为 2048 / 1536 / 1024（默认）/ 768 / 512 / 256 / 128 / 64。

## 两处必须由我们自己守住的东西

**1. 超时。** `TextEmbedding.call` → `BaseApi.call` 这一路上**没有任何 timeout
参数**（已核源码），底层的 `requests` 同样没有默认超时。网络黑洞会让解析线程
无限等待 —— 表现是「这份文档一直显示解析中」，重启才恢复。
所以这里外包一层有界线程池 + `future.result(timeout=...)`，做法与
`app/llm/search/agent.py` 对 tavily 的处理一致（那边也是上游无超时）。
⚠️ 残余风险相同：超时后那个线程不会被回收，`requests` 可能仍挂着。
这是**可预测的降级**，不是无界增长。

**2. 批量条数。** 上游对单次请求的条数有上限，超限是**直接失败**而不是截断。

⚠️ 2026-09-24 用真实 key 实测（`text-embedding-v4`）：n=10 成功，n=11 即返
`400 InvalidParameter: batch size is invalid, it should not be larger than 10`，
之后 12/16/20/25/26/50 一律同一个 400。⇒ **上限恰好是 10，而默认配置就是 10**，
即「刚好贴住上限、不能再调大」。这条也解释了为什么超限要显式报错：
上游不截断，它是整次调用失败 —— 一次超限 = 整份文档判为解析失败。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from langchain_core.embeddings import Embeddings

from app.core.config import Settings
from app.core.exceptions import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

#: 向量化用的线程池。**必须有界**：超时的线程不会被回收（见模块 docstring 第 1 条）。
#: 取 2 是因为解析池本身只有 2 个 worker，再多的并发只是把连接数堆在同一个上游上。
EMBED_POOL_MAX_WORKERS = 2

_pool: ThreadPoolExecutor | None = None


def get_embed_pool() -> ThreadPoolExecutor:
    """模块级线程池（懒建）。整个进程共用一个，避免每次调用新建池。"""
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=EMBED_POOL_MAX_WORKERS, thread_name_prefix="kb-embed")
    return _pool


class EmbeddingError(RuntimeError):
    """向量化失败。

    刻意不抛 `AppError`：这个异常产生在**后台解析线程**里，那里没有请求上下文，
    统一错误信封（`{code, message, data}`）无从谈起。调用方（`kb_service`）
    负责把它转成文档的失败状态与可展示文案。
    """


def parse_embeddings(output: object, *, expected: int) -> list[list[float]]:
    """把上游返回体解析成向量列表。

    ⚠️ **两种形态都要支持**：带 `text_index` 的（可能乱序），以及纯数组顺序的。
    `text_index` 是**服务端**给的字段，SDK 完全不解析返回体 ——
    所以「它一定有序」这个假设没有任何依据。

    ⚠️ 条数对不上必须报错，不能按短的截断：那意味着「哪一段对应哪个向量」
    已经不确定了，静默错配的后果是某些片段被安到别的文本上，而这种事
    在外部完全看不出来。
    """
    if not isinstance(output, dict):
        raise EmbeddingError(f"向量化返回体不是对象：{type(output).__name__}")

    items = output.get("embeddings")
    if not isinstance(items, list):
        raise EmbeddingError(f"向量化返回体缺少 embeddings 列表：keys={list(output)}")
    if len(items) != expected:
        raise EmbeddingError(f"向量化返回条数不符：期望 {expected}，实际 {len(items)}")

    parsed: list[tuple[int, list[float]]] = []
    for fallback_index, item in enumerate(items):
        if not isinstance(item, dict):
            raise EmbeddingError(f"向量化返回项不是对象：{type(item).__name__}")
        vector = item.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise EmbeddingError("向量化返回项缺少 embedding")
        # `bool` 是 `int` 的子类，要显式排除，否则 True 会被当成下标 1
        index = item.get("text_index")
        if not isinstance(index, int) or isinstance(index, bool):
            index = fallback_index
        parsed.append((index, [float(value) for value in vector]))

    parsed.sort(key=lambda pair: pair[0])
    return [vector for _, vector in parsed]


def _invoke_call(
    *,
    model: str,
    texts: list[str],
    text_type: str,
    dimension: int,
    api_key: str,
    timeout: float,
) -> list[list[float]]:
    """真正调上游，返回解析后的向量列表。

    ⚠️ **独立成一个函数是为了让测试能替身它** —— 与 conftest 里
    「绝不允许测试发出真实 LLM 请求」是同一条红线。
    """
    # 惰性导入：不开这个功能就完全不加载 SDK
    from dashscope import TextEmbedding

    try:
        response = get_embed_pool().submit(
            TextEmbedding.call,
            model=model,
            input=texts,
            text_type=text_type,
            dimension=dimension,
            api_key=api_key,
        ).result(timeout=timeout)
    except FuturesTimeout as exc:
        raise EmbeddingError(f"向量化调用超时（>{timeout}s，上游 SDK 无内建超时）") from exc
    except Exception as exc:  # noqa: BLE001 - 网络/序列化等任何异常都要可诊断
        raise EmbeddingError(f"{type(exc).__name__}: {exc}") from exc

    status = getattr(response, "status_code", None)
    if status != 200:
        code = getattr(response, "code", "")
        message = getattr(response, "message", "")
        raise EmbeddingError(f"向量化调用失败：status={status} code={code} message={message}")

    return parse_embeddings(getattr(response, "output", None), expected=len(texts))


class DashScopeEmbeddings(Embeddings):
    """LangChain 的 `Embeddings` 契约 → 百炼 `text-embedding-v4`。

    实现它而不是自己定一套接口，是为了让 `langchain-chroma` 能直接吃 ——
    否则「向量怎么进 Chroma」这块要自己拼一遍。
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.has_embedding_key:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "私有知识库还没配置向量化凭据（DASHSCOPE_API_KEY），请先在 .env 里填好",
                detail="dashscope_api_key empty but knowledge_base_enabled",
            )
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        # 至少 1，否则 range(0, n, 0) 会直接抛 ValueError
        self._batch = max(1, settings.embedding_batch_size)
        self._timeout = float(settings.embedding_timeout_seconds)
        self._api_key = settings.dashscope_api_key.strip()

    @property
    def dim(self) -> int:
        """向量维度。

        它会被写进 collection 的元数据：**换维度不会报错**，只会让新写入的向量
        永远检不出来（老的 1024 维、新的 768 维，没法比），所以排查时需要一个
        「这个库是按几维建的」的落点。
        """
        return self._dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """入库文本 → 向量。自动按批量上限切分，并**保持输入顺序**。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            vectors.extend(self._call(texts[start : start + self._batch], text_type="document"))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """检索查询 → 向量。单条，不分批。"""
        return self._call([text], text_type="query")[0]

    def _call(self, texts: list[str], *, text_type: str) -> list[list[float]]:
        """统一的调用入口：把任何异常都归一成 `EmbeddingError`。

        归一的意义在调用方一侧：`kb_service` 只需要捕一种异常就能给出
        「这份文档没能解析成功」的结论，而不用把 dashscope 的异常类型
        一个个列出来（列不全的那个必然会漏）。
        """
        try:
            return _invoke_call(
                model=self._model,
                texts=texts,
                text_type=text_type,
                dimension=self._dim,
                api_key=self._api_key,
                timeout=self._timeout,
            )
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001 - 契约要求：对外只有 EmbeddingError
            raise EmbeddingError(f"{type(exc).__name__}: {exc}") from exc


def build_embeddings(settings: Settings) -> Embeddings:
    """构造向量化器。

    Raises:
        AppError(5000): 未配置 `DASHSCOPE_API_KEY`。

    在这里就失败（而不是等解析到一半才报）的理由，与
    `TavilySearchProvider.__init__` 校验 key 完全一致：让「配置没配好」
    在**开始建库**这一步就暴露，而不是用户传完一份大文件、等十几秒后
    收到一句「解析失败」。
    """
    return DashScopeEmbeddings(settings)
