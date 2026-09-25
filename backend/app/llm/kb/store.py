"""向量库存储层：写入 / 检索 / 删除，以及**唯一**一处的隔离过滤。

## 隔离为什么必须收在一个文件、一个函数里

检索范围由两个条件共同决定：

1. **落在哪个 collection** —— 每用户一个 `user_{id}`，这是「跨用户」的边界；
2. **`where={"kb_id": ...}`** —— 这是「同一用户跨知识库」的边界。

两个条件缺任何一个都会泄漏，而且**都不会报错**：A 用户出题时会拿到 B 用户的资料，
表现只是「题目怪怪的」。所以调用方**不允许**自己拼 `where` ——
`search_chunks()` 是本模块对外唯一的检索入口，过滤条件写死在它里面。
新增检索场景时改这个函数，而不是在调用处复制一份过滤条件。

## 为什么用 `delete(where=...)` 而不是删 collection

⚠️ 实测（`langchain-chroma` 1.1.0 / `chromadb` 1.5.9）：

* `Chroma.delete()` 的签名只有 `(ids, **kwargs)`，而 `**kwargs` 会原样转给
  chromadb 的 `Collection.delete(ids, where, where_document)` —— 所以
  `delete(where={"kb_id": ...})` 能用；但**别写 `filter=`**，
  那是 `similarity_search*` 的参数名，传到 `delete` 会直接 `TypeError`（踩过）。
* `delete_collection()` 能删掉整个 collection —— **绝不能用它删库**：
  一个 collection 里装的是**这个用户的全部知识库**，用它删单个库会把
  其它库一起抹掉。只有「注销用户」这种整账号清理才轮到它（本期不做）。

## collection 名的硬约束

⚠️ 实测 Chroma 会拒掉长度 < 3 的集合名
（`InvalidArgumentError: Expected a name containing 3-512 characters`），
所以 `user_1` 合法而 `u1` 不行。`collection_name()` 是唯一的名字来源，
测试里也钉了这条规则。

## ⚠️ 为什么 client 必须进程级共享（2026-09-24 实测，并发解析必然踩到）

`chromadb` 的 system 是**按路径的进程级单例**（`SharedSystemClient._identifier_to_system`），
而 `Chroma(persist_directory=...)` 每次构造都会新建一个 `PersistentClient`。
两个线程同时构造时，其中一个的失败清理（`_release_system` → `system.stop()`）
会把另一个**正在使用**的 system 拆掉，实测两条症状：

* `AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'`
  （对方把 `bindings` 删了，这边正在读）；
* `KeyError: '<vectorstore 路径>'`（共享缓存里那条记录已被删）。

后果不是一条报错，而是**两份文档一起落到 `failed`**，而对用户的文案是那句
通用的「知识库服务暂时不可用」—— 从界面上完全看不出是并发问题。

⚠️ 注意它的影响面**不限于同一用户**：缓存按**路径**索引，而全后端只用一个
`vectorstore_path`，所以「A 用户解析 + B 用户检索」也会互踩。

所以 client 走 `_shared_client()`：**每个路径只构造一次**，之后所有人共用。
`langchain_chroma` 支持传入外部 `client`（第 369 行），且它与 `persist_directory`
互斥（同时给会 `ValueError`）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: 相似度度量。文本向量用余弦（与维度无关、只看方向），是 embedding 检索的常规选择。
#: ⚠️ 它只在**建 collection 时**生效：以后改这个值对已存在的 collection 是**静默无效**的
#: （实测重开时新元数据被忽略、旧的保留），要换度量只能重建 collection。
_HNSW_SPACE = "cosine"

#: 进程级共享的 chromadb client，按向量库路径索引。
#:
#: ⚠️ 必须共享，不能每次 `_open()` 现建 —— chromadb 的 system 是按路径的
#: 进程级单例，重复构造会在并发时互相拆台（见模块 docstring）。
_clients: dict[str, object] = {}
_clients_lock = threading.Lock()


def _shared_client(settings: Settings) -> object:
    """拿到（必要时创建）这个向量库路径上的共享 client。

    按**路径**缓存而不是按用户：chromadb 的 system 按路径索引，按用户缓存
    仍会让两个用户各自构造一个 —— 踩的正是这个坑。

    双检加锁：并发首次访问时只有一个线程真正构造，其余等它建好直接复用。
    """
    key = str(settings.vectorstore_path)
    cached = _clients.get(key)
    if cached is not None:
        return cached

    with _clients_lock:
        cached = _clients.get(key)  # 等锁期间别人可能已经建好
        if cached is None:
            import chromadb  # 惰性导入，理由同 `_open()`

            cached = chromadb.PersistentClient(path=key)
            _clients[key] = cached
    return cached


def collection_name(user_id: int) -> str:
    """这个用户的 collection 名。

    ⚠️ 这是**跨用户隔离的唯一实现点**，不要在任何别处拼这个名字。
    前缀取 `user_` 而不是 `u` —— 实测 Chroma 拒绝长度小于 3 的名字（见模块 docstring）。
    """
    return f"user_{int(user_id)}"


@dataclass(frozen=True, slots=True)
class KbChunk:
    """一条命中的知识片段。

    Attributes:
        text: 片段正文。
        kb_id / doc_id: 它属于哪个库、哪份文档。
        chunk_index: 在文档里的序号。伪 URL（design D6）要用它区分同一文档的不同片段。
        filename: 展示用的文件名 —— 出题 Prompt 里说「来源：你的知识库《{filename}》」。
        distance: 余弦距离，**越小越相关**。仅用于排序与日志，不进 Prompt。
    """

    text: str
    kb_id: int
    doc_id: int
    chunk_index: int
    filename: str
    distance: float


def _open(
    user_id: int,
    settings: Settings,
    embeddings: Embeddings | None,
) -> object:
    """打开（必要时创建）这个用户的向量集合。

    ⚠️ **惰性导入** `langchain_chroma`：它一导入就会拉起 chromadb
    （实测 `import chromadb` 1.31s / `import langchain_chroma` 1.78s）。
    功能开关关掉时不该付这个代价 —— 这是 `KNOWLEDGE_BASE_ENABLED` 默认关的
    意义之一（见 `requirements.txt` 里的体积说明）。

    `embeddings` 允许为 `None`：删除路径不需要向量化，此时同样不该去构造
    一个需要 API key 的向量化器（否则「删文档」会因为缺 key 而失败）。
    """
    from langchain_chroma import Chroma  # 惰性导入

    return Chroma(
        # ⚠️ 传共享 `client` 而不是 `persist_directory`：后者每次都会新建
        # `PersistentClient`，并发时两个线程会互相拆掉对方的 system
        # （见模块 docstring）。两者互斥，同时给会 ValueError。
        client=_shared_client(settings),
        collection_name=collection_name(user_id),
        embedding_function=embeddings,
        collection_metadata={
            "hnsw:space": _HNSW_SPACE,
            # 记录建库时的维度，供排查用（design D4）。改配置**不会**刷新它 ——
            # 这正是它有用的地方：能看出「库是老的维度建的」。
            "embedding_dim": int(settings.embedding_dim),
        },
    )


def chunk_id(doc_id: int, chunk_index: int) -> str:
    """片段的主键。

    用 `{doc_id}:{chunk_index}` 而不是自增 id：**同一文档重新解析时天然覆盖**，
    不追加（见 `add_chunks`）。用随机 id 的话，重试一次就在库里留下两份副本，
    检索结果里会出现两条一模一样的片段，而「命中 4 条」里有一半是重复的。
    """
    return f"{int(doc_id)}:{int(chunk_index)}"


def add_chunks(
    *,
    settings: Settings,
    embeddings: Embeddings,
    user_id: int,
    kb_id: int,
    doc_id: int,
    filename: str,
    chunks: list[str],
) -> int:
    """把一份文档的片段写入向量库，返回实际写入的条数。

    ⚠️ **先删后写**（不是直接 upsert）。实测踩过：`add_texts` 只 upsert 它拿到的
    id，所以当重新解析产出的片段**比上一次少**时，多出来的那些旧 id 会留在库里 ——
    症状是「重新解析过之后，检索还会命中已经被删掉的那一节」，而且不报错。
    多花一次按元数据删除，换「重新解析 = 完全覆盖」这个能说清楚的契约。

    ⚠️ 空列表**必须早退**：实测 Chroma 收到空列表会抛
    `ValueError: Expected Embeddings to be non-empty list or numpy array`。
    而「这份文档一个片段都没切出来」要在上层判成解析失败，不该在这里炸成 500。
    早退放在删除**之前**：空片段时上层会把文档判为失败，此时不该顺手把旧向量清掉。
    """
    if not chunks:
        return 0

    store = _open(user_id, settings, embeddings)
    # 清掉这份文档上一次解析留下的全部片段（见 docstring 的「先删后写」）
    store.delete(where={"doc_id": int(doc_id)})  # type: ignore[attr-defined]

    metadatas = [
        {
            "kb_id": int(kb_id),
            "doc_id": int(doc_id),
            "chunk_index": index,
            "filename": filename,
        }
        for index in range(len(chunks))
    ]
    ids = [chunk_id(doc_id, index) for index in range(len(chunks))]
    store.add_texts(texts=list(chunks), metadatas=metadatas, ids=ids)  # type: ignore[attr-defined]
    logger.info(
        "知识库写入：user=%s kb=%s doc=%s chunks=%s", user_id, kb_id, doc_id, len(chunks)
    )
    return len(chunks)


def search_chunks(
    *,
    settings: Settings,
    embeddings: Embeddings,
    user_id: int,
    kb_id: int,
    query: str,
    top_k: int | None = None,
) -> list[KbChunk]:
    """在**这个用户的这个库**里检索。本模块唯一的检索入口。

    隔离的两个条件都在这里落实：collection 由 `user_id` 决定、
    `where` 写死成 `kb_id`。调用方不需要（也不应该）知道这两件事。

    Args:
        query: 检索语句。空白时直接返回空，且**不发起**向量化调用 ——
            那是花钱的外部调用，而空查询的结果必然没有意义。
        top_k: 取几条；不传则用 `settings.kb_search_top_k`。`<= 0` 视为不取。

    Returns:
        按相关度从近到远排序的片段列表；没有命中时是空列表。
    """
    if not query or not query.strip():
        return []
    limit = int(settings.kb_search_top_k if top_k is None else top_k)
    if limit <= 0:
        return []

    store = _open(user_id, settings, embeddings)
    # ⚠️ `filter` 这个名字只属于 similarity_search*；同一个 where 语义在 delete 上
    # 叫 `where`。两者不能互换（见模块 docstring）。
    pairs = store.similarity_search_with_score(  # type: ignore[attr-defined]
        query,
        k=limit,
        filter={"kb_id": int(kb_id)},
    )
    chunks = [_to_chunk(document, score) for document, score in pairs]
    logger.info(
        "知识库检索：user=%s kb=%s top_k=%s 命中=%s", user_id, kb_id, limit, len(chunks)
    )
    return chunks


def _to_chunk(document: object, distance: float) -> KbChunk:
    """把 LangChain 的 `Document` 转成 `KbChunk`。

    元数据一律用 `.get` 兜底：这些字段是我们自己写进去的，但**旧数据可能没有**——
    上线后改元数据结构时，缺字段的旧片段不该让整个检索抛 `KeyError`
    （症状会是「这个库突然检不出东西」，而库里明明有内容）。
    """
    metadata = getattr(document, "metadata", {}) or {}
    return KbChunk(
        text=getattr(document, "page_content", "") or "",
        kb_id=int(metadata.get("kb_id", 0)),
        doc_id=int(metadata.get("doc_id", 0)),
        chunk_index=int(metadata.get("chunk_index", 0)),
        filename=str(metadata.get("filename", "")),
        distance=float(distance),
    )


def delete_document(*, settings: Settings, user_id: int, doc_id: int) -> None:
    """删掉一份文档的全部向量。

    不存在时静默返回：归属校验已经在数据库层做过，走到这里还报错只会把
    一个「已经删掉了」的正常情况变成 500。
    """
    store = _open(user_id, settings, None)
    store.delete(where={"doc_id": int(doc_id)})  # type: ignore[attr-defined]
    logger.info("知识库删除文档向量：user=%s doc=%s", user_id, doc_id)


def delete_base(*, settings: Settings, user_id: int, kb_id: int) -> None:
    """删掉一个知识库的全部向量（**不动**该用户的其它库）。

    ⚠️ 不要改用 `delete_collection()` —— 那个 collection 装的是这个用户的
    **所有**知识库，用它删单个库会把别的库一起抹掉（见模块 docstring）。
    """
    store = _open(user_id, settings, None)
    store.delete(where={"kb_id": int(kb_id)})  # type: ignore[attr-defined]
    logger.info("知识库删除库向量：user=%s kb=%s", user_id, kb_id)


def count_chunks(*, settings: Settings, user_id: int, kb_id: int | None = None) -> int:
    """数一数有多少片段（可按库过滤）。给测试与排查用，不参与业务判定。"""
    store = _open(user_id, settings, None)
    where = {"kb_id": int(kb_id)} if kb_id is not None else None
    result = store.get(where=where)  # type: ignore[attr-defined]
    return len(result.get("ids") or [])


def stored_embedding_dim(*, settings: Settings, user_id: int) -> int | None:
    """读回 collection 里记录的建库维度（design D4 的排查落点）。

    没有记录时返回 `None` —— 不去猜一个值出来。
    """
    store = _open(user_id, settings, None)
    metadata = getattr(store, "_collection", None)
    metadata = getattr(metadata, "metadata", None) or {}
    value = metadata.get("embedding_dim")
    return int(value) if isinstance(value, int) else None
