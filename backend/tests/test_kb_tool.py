"""`kb_search` 工具 —— 交给取材 Agent 的**第三个工具**（design D1 / D8）。

## 这个工具与 `tavily_*` 的三个不同

| | `tavily_search` / `tavily_extract` | `kb_search` |
|---|---|---|
| 检索范围 | 全网 | **只有这个用户、这一个库** |
| 返回形态 | 上游决定的三种形态（见 `collector.py`） | **我们自己定的**：`{query, results:[...]}` |
| 失败时 | 抛异常（`handle_tool_error=False`） | **返回错误体**，不抛 |

第三行是刻意的：这个工具是我们自己写的，没有理由把「失败」表达成「异常」——
而异常在这条链路上要多走一层（`agent._invoke_tool` 捕获 → `ok=False`）。
返回错误体走的是**已经存在**的那条路（`collector` 认得 `error` 键，见 design D6 第 1 条），
语义更直白：模型也会看到「这次没查到，别拿记忆凑」。

## `results` 里的 url 是**伪 URL**（design D6）

知识片段没有网址，但 `SearchResult.url` 是必填的，而且 `collector._dedupe()`
按 url 去重 —— 同一份文档的不同片段必须能被区分开，所以用
`kb://{kb_id}/{doc_id}#{chunk_index}`，**不能**用文件名（那会把一份文档的所有片段
合成一条）。`source` 与 `kind` 也一并由工具决定：`kb` / `snippet`（design D5）。

## 为什么这里能真跑数据库

知识库检索是本能力的核心，用替身替掉它等于把「能不能查到」这件事整段跳过。
所以本文件用**真的测试库 + 真的 Chroma（临时目录）+ 假的向量化**：
唯一的外部调用被换掉，隔离过滤与返回映射全部真跑。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.llm.kb import store as kb_store
from app.llm.kb.tools import KB_TOOL_NAME, build_kb_tool
from app.llm.search.base import KB_URL_PREFIX, KbScope, SearchRequest, kb_url
from app.services import kb_repository, kb_service
from tests.helpers import BagEmbeddings, make_user, user_id_of

CHUNKS = (
    "监督学习是从标注数据中学习映射函数的一类方法。",
    "无监督学习不依赖标注数据，靠数据自身的结构聚类。",
    "强化学习通过与环境交互获得奖励信号来学习策略。",
    "过拟合指模型在训练集上表现好、在新数据上表现差。",
    "正则化是用来抑制过拟合的常见手段。",
    "交叉验证把数据切成多份，轮流做验证集。",
)


@pytest.fixture(autouse=True)
def _kb(kb_harness):  # noqa: ANN001, ANN201, ARG001
    """本文件每条用例都在「知识库已开启 + 假向量化 + 会话指向测试库」的环境里跑。"""
    return kb_harness


@pytest.fixture
def user(db_session):  # noqa: ANN001, ANN201
    return make_user(db_session, openid="kb-tool-1")


@pytest.fixture
def other_user(db_session):  # noqa: ANN001, ANN201
    return make_user(db_session, openid="kb-tool-2", nickname="另一个人")


def _seed(
    session,  # noqa: ANN001
    settings: Settings,
    user,  # noqa: ANN001
    *,
    name: str = "资料库",
    chunks: tuple[str, ...] = CHUNKS,
    ready: bool = True,
    filename: str = "机器学习讲义.md",
) -> tuple[int, int]:
    """造一个库 + 一份文档（可选是否已是「已就绪」），并写入向量。

    直接走仓库层与存储层，**不经过上传/解析链** —— 那两段已经被
    `test_kb_service.py` 钉住了，这里要验的是「检索出来长什么样」。
    """
    owner = user_id_of(user)
    base = kb_repository.create_base(session, user_id=owner, name=name)
    doc = kb_repository.create_document(
        session, kb_id=int(base.id), user_id=owner, filename=filename, ext="md", size_bytes=1024
    )
    if ready:
        kb_repository.mark_ready(session, doc, chunk_count=len(chunks))
    session.commit()

    if ready:
        kb_store.add_chunks(
            settings=settings,
            embeddings=BagEmbeddings(),
            user_id=owner,
            kb_id=int(base.id),
            doc_id=int(doc.id),
            filename=filename,
            chunks=list(chunks),
        )
    return int(base.id), int(doc.id)


def _tool(settings: Settings, *, user_id: int, kb_id: int):  # noqa: ANN201
    request = SearchRequest(query="监督学习", kb=KbScope(user_id=user_id, kb_id=kb_id))
    return build_kb_tool(request, settings)


# -----------------------------------------------------------------------------
# 工具元信息
# -----------------------------------------------------------------------------
def test_pseudo_url_format_is_fixed() -> None:
    """伪 URL 的拼法只有一处实现，格式写死（design D6）。

    它是**跨模块字面量**：`llm/kb/tools.py` 拼、`collector._source_for()` 认。
    两处各写一份字符串，改一处就会让知识库片段被误判成网页资料。
    """
    assert kb_url(kb_id=7, doc_id=12, chunk_index=3) == "kb://7/12#3"
    assert KB_URL_PREFIX == "kb://"


def test_tool_name_and_description(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """名字必须与 `collector` 的白名单、`agent` 的分支三处一致。

    描述要让模型知道**只在用户自己的资料里找** —— 模型看不到我们的代码，
    它只会按描述判断该不该调这个工具。
    """
    tool = _tool(settings, user_id=user_id_of(user), kb_id=1)

    assert tool.name == KB_TOOL_NAME == "kb_search"
    assert "自己" in tool.description or "上传" in tool.description, tool.description
    assert "资料" in tool.description or "文档" in tool.description, tool.description


def test_tool_is_not_built_without_a_scope(settings: Settings) -> None:
    """没有指定库 → **不建工具**。

    这条挡住的是「大厅普通出题也绑上 kb_search」这种情况：工具一旦绑上去，
    模型就会去调，而库里根本没有本次要用的资料，用户会看到一份莫名其妙的题。
    """
    request = SearchRequest(query="监督学习")

    assert request.has_kb is False
    assert build_kb_tool(request, settings) is None


def test_tool_is_not_built_when_the_feature_is_disabled(settings: Settings) -> None:
    """**功能开关关掉 → 不建工具**（design D7 的实现点）。

    这里刻意用「带了库」的请求去试：开关必须压过请求 ——
    否则关掉开关的部署，只要请求里带了库，取材链照样会去查向量库，
    而 `llm/kb/` 在那种部署下根本不该被加载。

    为什么选在 `build_kb_tool` 这一处落地：它是**唯一的工具构造入口**
    （Tavily 与 Noop 都调它）。改这一处就自动统一了
    `run_search_agent` 里 `kb_tool is not None` 的判定与 `initial_step` 的进度名 ——
    两处各判一次迟早会漂移，那正是「进度卡说检索知识库、实际一次没查」的成因。
    """
    off = settings.model_copy(update={"knowledge_base_enabled": False})
    request = SearchRequest(query="监督学习", kb=KbScope(user_id=1, kb_id=1))

    assert request.has_kb is True, "前提：请求确实带了库，否则这条测试就没意义了"
    assert build_kb_tool(request, off) is None


# -----------------------------------------------------------------------------
# 命中
# -----------------------------------------------------------------------------
def test_hit_returns_pseudo_url_and_source(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """命中的片段要带得出**来源标识**：哪个库、哪份文档、第几段（spec 的检索契约）。"""
    owner = user_id_of(user)
    kb_id, doc_id = _seed(db_session, settings, user)

    payload = _tool(settings, user_id=owner, kb_id=kb_id).invoke({"query": "监督学习"})

    assert isinstance(payload, dict)
    assert payload["results"], payload
    item = payload["results"][0]
    assert item["url"].startswith(f"{KB_URL_PREFIX}{kb_id}/{doc_id}#"), item["url"]
    assert item["source"] == "kb"
    assert item["kind"] == "snippet"
    # 标题是文件名 —— `as_reference()` 靠它渲染「你的知识库《X》」
    assert item["title"] == "机器学习讲义.md"
    assert item["content"] in CHUNKS, item["content"]


def test_every_chunk_gets_a_distinct_url(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """一份文档的多个片段必须各有各的 url —— 否则 `collector._dedupe()` 会把它们合成一条。"""
    owner = user_id_of(user)
    kb_id, doc_id = _seed(db_session, settings, user)
    tool = _tool(settings, user_id=owner, kb_id=kb_id)

    payload = tool.invoke({"query": "学习"})

    urls = [item["url"] for item in payload["results"]]
    assert len(urls) == len(set(urls)), urls
    assert all(url.startswith(f"{KB_URL_PREFIX}{kb_id}/{doc_id}#") for url in urls), urls


def test_result_count_is_capped_by_top_k(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """条数上限是**独立于网页检索**的配置（spec：「两者内容形态不同」）。"""
    owner = user_id_of(user)
    kb_id, _ = _seed(db_session, settings, user)
    strict = settings.model_copy(update={"kb_search_top_k": 2})

    payload = _tool(strict, user_id=owner, kb_id=kb_id).invoke({"query": "学习"})

    assert 0 < len(payload["results"]) <= 2, payload


# -----------------------------------------------------------------------------
# 隔离
# -----------------------------------------------------------------------------
def test_other_base_of_the_same_user_is_not_returned(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """**同一个人**的另一个库也不能串味 —— 这是 `where={"kb_id": ...}` 那条边界。"""
    owner = user_id_of(user)
    target, _ = _seed(db_session, settings, user, name="要检索的库")
    _seed(db_session, settings, user, name="不该出现的库", chunks=("这是另一个库里的内容。",))

    payload = _tool(settings, user_id=owner, kb_id=target).invoke({"query": "学习"})

    texts = {item["content"] for item in payload["results"]}
    assert "这是另一个库里的内容。" not in texts, payload


def test_other_users_chunks_are_not_returned(settings: Settings, db_session, user, other_user) -> None:  # noqa: ANN001, ARG001
    """跨用户也不行 —— 这是 collection `user_{id}` 那条边界。"""
    owner = user_id_of(user)
    mine, _ = _seed(db_session, settings, user, name="我的库")
    _seed(db_session, settings, other_user, name="我的库", chunks=("别人的机密资料。",))

    payload = _tool(settings, user_id=owner, kb_id=mine).invoke({"query": "学习"})

    texts = {item["content"] for item in payload["results"]}
    assert "别人的机密资料。" not in texts, payload


# -----------------------------------------------------------------------------
# 没命中 / 空库 / 失败 —— 三种都要能分辨
# -----------------------------------------------------------------------------
def test_empty_base_is_distinguishable_from_no_hit(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """「库是空的」与「检索没命中」是两件事（spec 明确要求能区分）。

    空库带上 `note` 说清原因 —— 模型据此知道「不是搜不到，是还没有资料」，
    从而不会在结束语里说「资料已足够」。
    """
    owner = user_id_of(user)
    kb_id, _ = _seed(db_session, settings, user, ready=False)

    payload = _tool(settings, user_id=owner, kb_id=kb_id).invoke({"query": "监督学习"})

    assert payload["results"] == []
    assert payload.get("note"), "空库必须给 model 一句话说明，否则它分不清「空」与「没搜到」"
    assert "解析" in payload["note"] or "就绪" in payload["note"] or "资料" in payload["note"], payload


def test_blank_query_does_not_call_the_vectorizer(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """空查询直接返回空 —— 向量化是**花钱的外部调用**，不该为它发一次。"""
    owner = user_id_of(user)
    kb_id, _ = _seed(db_session, settings, user)
    calls: list[str] = []

    class CountingEmbeddings(BagEmbeddings):
        def embed_query(self, text: str) -> list[float]:
            calls.append(text)
            return super().embed_query(text)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(kb_service, "_build_embeddings", lambda _s: CountingEmbeddings())
    try:
        payload = _tool(settings, user_id=owner, kb_id=kb_id).invoke({"query": "   "})
    finally:
        monkeypatch.undo()

    assert payload["results"] == []
    assert calls == [], "空查询不该触发向量化"


def test_failure_is_returned_as_an_error_body_not_raised(
    settings: Settings, db_session, user, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001
) -> None:
    """检索炸了 → **返回错误体**，不抛异常。

    取材链的契约是「取不到资料就降级」（`base.py` 模块头），而 `kb_search`
    是我们自己写的工具，没有理由把失败表达成异常 —— 返回错误体走的是
    `collector` 已经认得的那条路（`error` 键），模型也会看到「这次没查到」。
    """
    owner = user_id_of(user)
    kb_id, _ = _seed(db_session, settings, user)

    def _boom(**kwargs: object) -> None:
        raise RuntimeError("vector store exploded")

    monkeypatch.setattr(kb_service, "search_for_tool", _boom)

    payload = _tool(settings, user_id=owner, kb_id=kb_id).invoke({"query": "监督学习"})

    assert isinstance(payload, dict)
    assert "results" not in payload or payload["results"] == []
    assert payload.get("error"), payload


def test_error_body_is_understood_by_the_collector(settings: Settings, db_session, user) -> None:  # noqa: ANN001
    """错误体必须能被**既有的**采集器判成失败 —— 这条钉住两个模块的形状契约。"""
    from app.llm.search.base import ReferenceCaps
    from app.llm.search.collector import ToolOutput, collect_results

    outputs = [ToolOutput(tool=KB_TOOL_NAME, payload={"error": "知识库检索失败"})]

    results = collect_results(
        outputs,
        request=SearchRequest(query="x"),
        caps=ReferenceCaps(),
    )

    assert results == (), "错误体不许被当成命中"
