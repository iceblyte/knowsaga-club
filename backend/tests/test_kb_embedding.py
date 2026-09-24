"""私有知识库的**向量化适配器**契约（`add-private-knowledge-base` 第 3 组）。

为什么这几条断言值得存在：向量化是建库链上**唯一的付费外部调用**，而它的两种
失败形态都是静默的 ——

* `text_type` 传错（入库文本用了 `query`）→ **不报错**，只是检索质量悄悄下降，
  表现为「明明传了这份资料，出题却总抓不到重点」；
* 单次条数超过上游上限 → 直接失败，整份文档判为「解析失败」，
  而用户只看到一句「没能解析成功」，看不出是批量太大还是文件坏了。

所以这两件事各有一条断言钉住，而不是靠评审看一眼。

`dashscope` 的真实调用**一律被替身接管**（`_invoke_call`）—— 与 conftest 里
「绝不允许测试发出真实 LLM 请求」是同一条红线。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import AppError
from app.llm.kb import embedding as embedding_mod
from app.llm.kb.embedding import (
    EmbeddingError,
    build_embeddings,
    parse_embeddings,
)

DIM = 8


def _settings(**over: object) -> Settings:
    """只读代码默认值的配置（断掉仓库根 `.env`，避免本机配置污染）。"""
    base = Settings(_env_file=None, dashscope_api_key="sk-test-not-real")
    return base.model_copy(update=over) if over else base


class FakeCaller:
    """替身：记录每次调用参数，按请求条数返回等量向量。"""

    def __init__(self, *, dim: int = DIM, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._dim = dim
        self._error = error

    def __call__(self, **kwargs: object) -> list[list[float]]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        texts = kwargs["texts"]
        assert isinstance(texts, list)
        # 用一个可辨认的取值，便于断言「顺序没有被打乱」
        return [[float(len(t)), *([0.0] * (self._dim - 1))] for t in texts]


@pytest.fixture
def fake_caller(monkeypatch: pytest.MonkeyPatch) -> FakeCaller:
    fake = FakeCaller()
    monkeypatch.setattr(embedding_mod, "_invoke_call", fake)
    return fake


# ---------------------------------------------------------------- 入库 vs 检索
def test_embed_documents_marks_text_type_document(fake_caller: FakeCaller) -> None:
    """入库的文本必须标 `document`。

    这是原生 SDK 相对 OpenAI 兼容端点的**唯一理由**：把语料与查询分别编码
    （asymmetric embedding）是 v4 的推荐用法，标错不报错、只掉召回质量。
    """
    emb = build_embeddings(_settings())
    emb.embed_documents(["第一段", "第二段"])

    assert len(fake_caller.calls) == 1
    assert fake_caller.calls[0]["text_type"] == "document"


def test_embed_query_marks_text_type_query(fake_caller: FakeCaller) -> None:
    """检索的查询必须标 `query`，且返回**单条**向量（不是嵌套列表）。"""
    emb = build_embeddings(_settings())
    vector = emb.embed_query("什么是 RAG")

    assert fake_caller.calls[0]["text_type"] == "query"
    assert len(vector) == DIM
    assert all(isinstance(x, float) for x in vector)


def test_same_model_and_dimension_both_paths(fake_caller: FakeCaller) -> None:
    """两条路径用同一个模型与同一个维度 —— 维度不一致会让向量根本没法比。"""
    emb = build_embeddings(_settings(embedding_model="text-embedding-v4", embedding_dim=DIM))
    emb.embed_documents(["甲"])
    emb.embed_query("乙")

    assert {c["model"] for c in fake_caller.calls} == {"text-embedding-v4"}
    assert {c["dimension"] for c in fake_caller.calls} == {DIM}


# ---------------------------------------------------------------- 分批
def test_embed_documents_splits_into_batches(fake_caller: FakeCaller) -> None:
    """25 条文本、批量 10 ⇒ 三次调用（10 + 10 + 5）。

    上游对单次条数有上限，超限是**直接失败**而不是截断。
    """
    emb = build_embeddings(_settings(embedding_batch_size=10))
    emb.embed_documents([f"第{i}段" for i in range(25)])

    assert len(fake_caller.calls) == 3
    assert [len(c["texts"]) for c in fake_caller.calls] == [10, 10, 5]


def test_embed_documents_keeps_input_order(fake_caller: FakeCaller) -> None:
    """分批之后顺序必须与输入一致 —— 片段位置错乱会让来源彻底对不上。"""
    texts = [f"第{i}段" * (i + 1) for i in range(7)]
    emb = build_embeddings(_settings(embedding_batch_size=3))

    vectors = emb.embed_documents(texts)

    assert len(vectors) == len(texts)
    # 替身把「文本长度」放在第 0 位，正好用来验证顺序
    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]


def test_embed_documents_empty_input_makes_no_call(fake_caller: FakeCaller) -> None:
    """空输入不发请求 —— 一次网络往返换一个空列表是纯浪费。"""
    emb = build_embeddings(_settings())

    assert emb.embed_documents([]) == []
    assert fake_caller.calls == []


# ---------------------------------------------------------------- 失败
def test_upstream_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游异常被包成 `EmbeddingError`，且**保留原因**（供日志与失败分类）。"""
    fake = FakeCaller(error=RuntimeError("connection reset"))
    monkeypatch.setattr(embedding_mod, "_invoke_call", fake)
    emb = build_embeddings(_settings())

    with pytest.raises(EmbeddingError) as excinfo:
        emb.embed_documents(["甲"])

    assert "connection reset" in str(excinfo.value)


def test_build_embeddings_requires_key() -> None:
    """未配置凭据时**立刻**抛 5000，而不是等到第一次调用才失败。

    理由同 `TavilySearchProvider` 在构造时校验 key：让用户在「开始建库」这一步
    就看到配置问题，而不是上传完一份大文件、等十几秒后收到「解析失败」。
    """
    with pytest.raises(AppError) as excinfo:
        build_embeddings(_settings(dashscope_api_key=""))

    assert excinfo.value.code == 5000


# ---------------------------------------------------------------- 返回体解析
def test_parse_embeddings_sorts_by_text_index() -> None:
    """返回体自带 `text_index` 时按它排序 —— 不能假设服务端一定有序。"""
    output = {
        "embeddings": [
            {"text_index": 1, "embedding": [2.0, 2.0]},
            {"text_index": 0, "embedding": [1.0, 1.0]},
        ]
    }

    assert parse_embeddings(output, expected=2) == [[1.0, 1.0], [2.0, 2.0]]


def test_parse_embeddings_falls_back_to_array_order() -> None:
    """没有 `text_index` 时按数组顺序取 —— 两种形态都要能work。"""
    output = {"embeddings": [{"embedding": [1.0]}, {"embedding": [2.0]}]}

    assert parse_embeddings(output, expected=2) == [[1.0], [2.0]]


def test_parse_embeddings_rejects_count_mismatch() -> None:
    """条数对不上必须报错。

    对不上意味着「哪一段对应哪个向量」已经不确定了 —— 静默按短的截断
    会让某些片段被错配到别的文本上，而那种错误没有任何外部迹象。
    """
    output = {"embeddings": [{"embedding": [1.0]}]}

    with pytest.raises(EmbeddingError):
        parse_embeddings(output, expected=3)


def test_parse_embeddings_rejects_missing_field() -> None:
    """返回体形状不对时给可诊断的错误，而不是 `KeyError`。"""
    with pytest.raises(EmbeddingError):
        parse_embeddings({"not_embeddings": []}, expected=1)
