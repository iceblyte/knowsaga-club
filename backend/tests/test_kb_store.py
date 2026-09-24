"""向量库存储层的隔离契约（`add-private-knowledge-base` 第 5 组）。

## 本文件在钉什么

`store.py` 是整个功能里**唯一**能把检索范围收窄到「这个人这个库」的地方。
它的失败模式全部是**静默的**：跨用户泄漏不会报错，只会让 A 用户出题时看到
B 用户资料里的内容；跨库泄漏同理，而两者在界面上都表现成「题目有点怪」。

所以这里用**真 Chroma**（临时目录 + 假向量化器）而不是 mock ——
过滤条件是拼给 Chroma 的 `where`，mock 掉它等于把唯一要验证的东西替身掉了。
假向量化器只负责把文本变成可比较的向量，且**不访问网络**（红线不变）。

## 为什么「同一用户的两个库」与「两个用户的同一个库 id」都要测

前者验证 `kb_id` 过滤真的生效；后者验证**隔离靠的是 collection 而不是 kb_id** ——
两个用户各自建的第一个库都会拿到 `kb_id` 很小的值，如果哪一天有人图省事
把 `user_id` 从 collection 名里拿掉、只靠 `kb_id` 过滤，这一条会立刻变红。
"""

from __future__ import annotations

import pytest
from langchain_core.embeddings import Embeddings

from app.llm.kb.store import (
    KbChunk,
    add_chunks,
    collection_name,
    count_chunks,
    delete_base,
    delete_document,
    search_chunks,
    stored_embedding_dim,
)

#: 假向量化的维度。小一点让测试快，但必须与 `EMBEDDING_DIM` 一致。
_FAKE_DIM = 32


class _BagEmbeddings(Embeddings):
    """字符袋向量：同字多的文本向量更接近。

    选它而不是「固定返回同一个向量」：那样任何查询都会命中文档，
    「检不到」的断言就永远是假的绿。字符袋至少让**距离有区分度**，
    于是「本该检到却没检到」才会暴露。

    同时它记录调用次数，用来验证「空白查询不该白白发一次向量化调用」。
    """

    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * _FAKE_DIM
        for char in text:
            vector[ord(char) % _FAKE_DIM] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self._vector(text)


@pytest.fixture
def embeddings() -> _BagEmbeddings:
    return _BagEmbeddings()


@pytest.fixture
def kb_settings(tmp_path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """向量库落临时目录、维度对齐假向量化器。"""
    from app.core.config import get_settings

    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vectorstore"))
    monkeypatch.setenv("EMBEDDING_DIM", str(_FAKE_DIM))
    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


def _seed(
    settings,  # noqa: ANN001
    embeddings: _BagEmbeddings,
    *,
    user_id: int,
    kb_id: int,
    doc_id: int,
    filename: str,
    chunks: list[str],
) -> None:
    add_chunks(
        settings=settings,
        embeddings=embeddings,
        user_id=user_id,
        kb_id=kb_id,
        doc_id=doc_id,
        filename=filename,
        chunks=chunks,
    )


def _search(settings, embeddings, *, user_id: int, kb_id: int, query: str, top_k: int | None = None):  # noqa: ANN001, ANN202, E501
    return search_chunks(
        settings=settings,
        embeddings=embeddings,
        user_id=user_id,
        kb_id=kb_id,
        query=query,
        top_k=top_k,
    )


# ---------------------------------------------------------------- 集合命名
def test_collection_name_is_per_user() -> None:
    assert collection_name(7) == "user_7"


@pytest.mark.parametrize("user_id", [1, 42, 999999])
def test_collection_name_is_accepted_by_chroma(user_id: int) -> None:
    """集合名必须满足 Chroma 的命名规则：3–512 字符、只含 `[a-zA-Z0-9._-]`。

    ⚠️ 这条不是凑数：实测 `u1` 这种短名字会被 Chroma 直接拒掉
    （`InvalidArgumentError: Expected a name containing 3-512 characters`），
    而报错发生在**创建集合**时 —— 也就是用户第一次上传文档的时候。
    所以名字格式要在有测试的地方定死，不能靠「反正 user_ 前缀够长」的运气。
    """
    name = collection_name(user_id)
    assert 3 <= len(name) <= 512
    assert name[0].isalnum() and name[-1].isalnum()
    assert all(char.isalnum() or char in "._-" for char in name)


# ---------------------------------------------------------------- 基本往返
def test_added_chunks_are_retrievable(kb_settings, embeddings, tmp_path) -> None:  # noqa: ANN001, ARG001
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="rag.pdf",
        chunks=["RAG 的核心是先检索再生成。", "向量检索按语义相似度召回。"],
    )

    hits = _search(kb_settings, embeddings, user_id=1, kb_id=7, query="检索")

    assert hits, "刚写进去的片段必须能检索到"
    assert all(isinstance(hit, KbChunk) for hit in hits)


def test_chunk_metadata_round_trips(kb_settings, embeddings) -> None:  # noqa: ANN001
    """片段必须带着「它从哪来」的全部信息 —— 出题链要拿它拼来源标识（D6）。"""
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="机器学习导论.pdf",
        chunks=["监督学习需要一个带标签的训练集。"],
    )

    hit = _search(kb_settings, embeddings, user_id=1, kb_id=7, query="监督学习")[0]

    assert hit.kb_id == 7
    assert hit.doc_id == 101
    assert hit.chunk_index == 0
    assert hit.filename == "机器学习导论.pdf"
    assert "监督学习" in hit.text


def test_results_are_ordered_by_relevance(kb_settings, embeddings) -> None:  # noqa: ANN001
    """结果按相关度从近到远 —— 截断（top_k）取的就是最前面那几条。"""
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["完全无关的一段话：今天天气不错。", "向量检索检索检索检索检索。"],
    )

    hits = _search(kb_settings, embeddings, user_id=1, kb_id=7, query="检索")

    assert len(hits) >= 2
    assert [hit.distance for hit in hits] == sorted(hit.distance for hit in hits)
    assert "检索" in hits[0].text


def test_top_k_limits_results(kb_settings, embeddings) -> None:  # noqa: ANN001
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=[f"第 {index} 段：检索相关的内容。" for index in range(6)],
    )

    assert len(_search(kb_settings, embeddings, user_id=1, kb_id=7, query="检索", top_k=2)) == 2


def test_top_k_zero_returns_nothing(kb_settings, embeddings) -> None:  # noqa: ANN001
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["检索相关的内容。"],
    )

    assert _search(kb_settings, embeddings, user_id=1, kb_id=7, query="检索", top_k=0) == []


# ---------------------------------------------------------------- 隔离（本文件的核心）
def test_search_never_crosses_libraries(kb_settings, embeddings) -> None:  # noqa: ANN001
    """同一用户的两个库之间必须互不可见。"""
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["这是七号库里的检索内容。"],
    )
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=8,
        doc_id=201,
        filename="b.md",
        chunks=["这是八号库里的检索内容。"],
    )

    hits = _search(kb_settings, embeddings, user_id=1, kb_id=7, query="检索内容")

    assert hits
    assert {hit.kb_id for hit in hits} == {7}
    assert all("七号库" in hit.text for hit in hits)


def test_search_of_unknown_library_returns_nothing(kb_settings, embeddings) -> None:  # noqa: ANN001
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["检索内容。"],
    )

    assert _search(kb_settings, embeddings, user_id=1, kb_id=999, query="检索内容") == []


def test_search_never_crosses_users(kb_settings, embeddings) -> None:  # noqa: ANN001
    """两个用户的**同一个 `kb_id`** 也必须互不可见。

    这是最要命也最容易写错的一种：隔离靠的是每用户一个 collection，
    而不是 `kb_id`（两个用户各自的第一个库，kb_id 都会是很小的值）。
    """
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="mine.md",
        chunks=["甲用户的私密检索资料。"],
    )
    _seed(
        kb_settings,
        embeddings,
        user_id=2,
        kb_id=7,
        doc_id=201,
        filename="yours.md",
        chunks=["乙用户的私密检索资料。"],
    )

    hits = _search(kb_settings, embeddings, user_id=1, kb_id=7, query="私密检索资料")

    assert hits
    assert all("甲用户" in hit.text for hit in hits)
    assert all("乙用户" not in hit.text for hit in hits)


def test_search_for_user_without_any_data_returns_nothing(kb_settings, embeddings) -> None:  # noqa: ANN001
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["检索内容。"],
    )

    assert _search(kb_settings, embeddings, user_id=2, kb_id=7, query="检索内容") == []


# ---------------------------------------------------------------- 删除
def test_delete_document_removes_only_that_document(kb_settings, embeddings) -> None:  # noqa: ANN001
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["甲文档的检索内容。"],
    )
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=202,
        filename="b.md",
        chunks=["乙文档的检索内容。"],
    )

    delete_document(settings=kb_settings, user_id=1, doc_id=101)

    hits = _search(kb_settings, embeddings, user_id=1, kb_id=7, query="检索内容")
    assert hits
    assert {hit.doc_id for hit in hits} == {202}
    assert count_chunks(settings=kb_settings, user_id=1, kb_id=7) == 1


def test_delete_base_removes_all_chunks_but_not_other_bases(kb_settings, embeddings) -> None:  # noqa: ANN001
    """删库要连向量一起清掉。

    只删数据库里那两行（`knowledge_bases` / `knowledge_documents`）而留下向量，
    症状是「库已经没了，出题时却还能引用它的内容」—— 而且是**静默的**，
    因为检索这一路根本不看数据库。
    """
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["七号库的检索内容。", "七号库的第二段。"],
    )
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=8,
        doc_id=201,
        filename="b.md",
        chunks=["八号库的检索内容。"],
    )

    delete_base(settings=kb_settings, user_id=1, kb_id=7)

    assert _search(kb_settings, embeddings, user_id=1, kb_id=7, query="检索内容") == []
    assert count_chunks(settings=kb_settings, user_id=1, kb_id=7) == 0
    assert count_chunks(settings=kb_settings, user_id=1, kb_id=8) == 1


def test_deleting_from_another_users_base_changes_nothing(kb_settings, embeddings) -> None:  # noqa: ANN001
    """越权删除必须只影响调用者自己的 collection。"""
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="mine.md",
        chunks=["甲的检索内容。"],
    )

    delete_base(settings=kb_settings, user_id=2, kb_id=7)

    assert count_chunks(settings=kb_settings, user_id=1, kb_id=7) == 1


def test_deleting_unknown_identifiers_is_quiet(kb_settings, embeddings) -> None:  # noqa: ANN001
    """删一个不存在的文档 / 库不该抛异常。

    调用方（删除接口）已经在数据库层做过归属校验，走到这里还报错只会
    把一个「已经删掉了」的正常情况变成 500。
    """
    delete_document(settings=kb_settings, user_id=1, doc_id=999999)
    delete_base(settings=kb_settings, user_id=1, kb_id=999999)


# ---------------------------------------------------------------- 幂等与边界
def test_readding_same_document_replaces_chunks(kb_settings, embeddings) -> None:  # noqa: ANN001
    """同一文档重新解析 = 覆盖，不是追加。

    解析失败重试、或者以后做「重新解析」时都会走这条路。追加的话，
    同一段内容会在库里存两份，检索结果里连着出现两条一模一样的片段，
    而「命中 4 条」里其实有一半是重复的。
    """
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["旧内容甲。", "旧内容乙。"],
    )
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["新内容。"],
    )

    assert count_chunks(settings=kb_settings, user_id=1, kb_id=7) == 1
    hits = _search(kb_settings, embeddings, user_id=1, kb_id=7, query="旧内容")
    assert all("旧内容" not in hit.text for hit in hits)


def test_empty_chunk_list_writes_nothing(kb_settings, embeddings) -> None:  # noqa: ANN001
    """空列表必须**早退**：实测 Chroma 收到空列表会抛
    `ValueError: Expected Embeddings to be non-empty list`，
    而「这份文档没切出片段」本该由上层判失败，不该在这里炸成 500。
    """
    written = add_chunks(
        settings=kb_settings,
        embeddings=embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=[],
    )

    assert written == 0
    assert embeddings.document_calls == 0, "没有内容就不该调用向量化"
    assert count_chunks(settings=kb_settings, user_id=1, kb_id=7) == 0


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_query_returns_nothing_without_embedding(kb_settings, embeddings, blank: str) -> None:  # noqa: ANN001
    """空白查询直接返回空，且**不发起**向量化调用。

    向量化是花钱的外部调用。查询为空（模型偶尔会这么调一次工具）时
    发出去，既浪费额度又必然得到一个无意义的结果。
    """
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["检索内容。"],
    )
    embeddings.query_calls = 0

    assert _search(kb_settings, embeddings, user_id=1, kb_id=7, query=blank) == []
    assert embeddings.query_calls == 0


def test_add_chunks_reports_written_count(kb_settings, embeddings) -> None:  # noqa: ANN001
    """返回实际写入条数 —— 它会作为 `chunk_count` 落库，界面上要显示。"""
    written = add_chunks(
        settings=kb_settings,
        embeddings=embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["甲。", "乙。", "丙。"],
    )

    assert written == 3
    assert count_chunks(settings=kb_settings, user_id=1, kb_id=7) == 3


# ---------------------------------------------------------------- 持久化与排查
def test_chunks_survive_reopen(kb_settings, embeddings) -> None:  # noqa: ANN001
    """写进去的内容在「重开一次」之后还在 —— 这也是解析状态必须落库的同一条理由
    （进程重启不该让已解析的资料消失）。"""
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["重启后仍应存在的检索内容。"],
    )

    fresh = _BagEmbeddings()
    hits = _search(kb_settings, fresh, user_id=1, kb_id=7, query="检索内容")

    assert hits


def test_stored_embedding_dim_is_recorded_and_survives(kb_settings, embeddings, monkeypatch) -> None:  # noqa: ANN001
    """collection 里记着「它是按几维建的」，而且**改配置不会改写它**。

    这是 design D4 留的排查落点：中途换 `EMBEDDING_DIM` 不会报错，
    只会让新写入的向量检不出来。有这条记录，就能一眼看出
    「库是 1024 维建的、现在配置是 768」—— 否则只能靠猜。
    """
    _seed(
        kb_settings,
        embeddings,
        user_id=1,
        kb_id=7,
        doc_id=101,
        filename="a.md",
        chunks=["甲。"],
    )
    assert stored_embedding_dim(settings=kb_settings, user_id=1) == _FAKE_DIM

    # 把配置改成另一个维度，再把连接重开一次
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    from app.core.config import get_settings

    get_settings.cache_clear()
    changed = get_settings()
    try:
        assert stored_embedding_dim(settings=changed, user_id=1) == _FAKE_DIM, (
            "collection 里记录的维度不该被后来的配置改写"
        )
    finally:
        get_settings.cache_clear()
