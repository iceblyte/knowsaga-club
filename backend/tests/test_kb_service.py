"""知识库服务层：准入、落盘、解析状态机、连带删除（`app/services/kb_service.py`）。

## 这里锁什么

spec 里那七条 Requirement 的**可测部分**基本都在本文件：

| spec Requirement | 本文件的用例 |
|---|---|
| 上传准入由格式与体积共同决定 | `test_*_rejected_*` |
| 上传立即返回，解析在后台 | `test_upload_returns_before_parse` |
| 解析状态是显式状态机，失败可诊断 | `test_parse_*` |
| 知识库与文档严格按用户隔离 | `test_*_other_users_*` |
| 检索契约 | `test_search_*` |
| 删除必须连带清掉向量数据 | `test_delete_*` |
| 向量化不可用时如实失败 | `test_parse_without_embedding_key_fails` |

## 三个替身，分别替掉三件不能真做的事

| 替身 | 替掉 | 为什么 |
|---|---|---|
| `kb_service._submit` | 后台线程池 | 真起线程会让「上传后状态是 pending」变成一个**竞态**断言（有时 pending、有时 ready） |
| `kb_service._build_embeddings` | 百炼向量化 | 单测**不许**发出真实外部请求（与「LLM 一律 mock」同一条红线）。本机虽已配好 `DASHSCOPE_API_KEY`，单测仍必须走替身 —— 真链路验证在浏览器 e2e 里单独做，不由这里代替 |
| `UPLOADS_DIR` / `VECTORSTORE_DIR` | 真实目录 | 否则每跑一次用例，仓库里就多一堆垃圾文档与向量库文件 |

⚠️ **`_submit` 被替换成「同步执行」时，上传流程必须先 `commit` 再提交解析** ——
解析线程用另一个连接读那一行，没提交它读不到，会安静地什么都不做。
这条约束由 `test_upload_returns_before_parse` 与
`test_parsing_state_is_visible_mid_flight` 两条一起钉住。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.constants import KB_DEFAULT_NAME
from app.core.exceptions import AppError, ErrorCode
from app.llm.kb import store as kb_store
from app.llm.kb.embedding import EmbeddingError
from app.llm.kb.loaders import LoadedDocument
from app.services import kb_repository, kb_service
from tests.helpers import fresh_snapshot, make_user, user_id_of

LONG_TEXT = "监督学习的核心是学习一个映射函数。" * 60
SHORT_TEXT = "监督学习是从标注数据中学习映射函数。"

#: 等后台线程的兜底上限。解析在测试里是「读一个 md 文件」，正常在毫秒级；
#: 真卡住时宁可失败，也不要挂死整个用例。
_WAIT_SECONDS = 10.0


def _wait_until(predicate, *, what: str, timeout: float = _WAIT_SECONDS) -> None:  # noqa: ANN001, ANN202
    """轮询等待一个条件成立（只用于「真的起了线程」那两条用例）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"等待超时（{timeout}s）：{what}")


# -----------------------------------------------------------------------------
# 夹具
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _kb(kb_harness):  # noqa: ANN001, ANN201
    """这个文件里**每一条**用例都在「知识库已开启 + 替身就位」的环境里跑。

    共用夹具在 `conftest.py`（`kb_env` / `kb_fake_embeddings` / `kb_session_scope`）；
    这里只做「本模块一律自动生效」这一件事 —— 漏掉一条就漏掉一次替身，
    而漏掉向量化替身的失败（网络不通、配额）看起来会像业务逻辑的问题。
    """
    return kb_harness


@pytest.fixture
def settings(kb_env):  # noqa: ANN001, ANN201, ARG001
    return kb_env()


@pytest.fixture
def inline_parse(kb_inline_parse):  # noqa: ANN001, ANN201, ARG001
    """名字保持本文件的读法，实现是共用夹具（见 conftest）。"""


@pytest.fixture
def user(db_session):  # noqa: ANN001, ANN201
    return make_user(db_session, openid="kb-svc-1")


@pytest.fixture
def other_user(db_session):  # noqa: ANN001, ANN201
    return make_user(db_session, openid="kb-svc-2", nickname="另一个人")



# -----------------------------------------------------------------------------
# 小工具
# -----------------------------------------------------------------------------
def _upload(session, user, *, filename, content: bytes = SHORT_TEXT.encode("utf-8"), kb_id=None):  # noqa: ANN001, ANN202
    return kb_service.upload_document(
        session, user, filename=filename, data=content, kb_id=kb_id
    )


def _base(session, user, *, name: str = "课程资料"):  # noqa: ANN001, ANN202
    return kb_service.create_base(session, user, name=name, description="")


def _doc_row(session, doc_id: int):  # noqa: ANN001, ANN202
    """**另起一个会话**读文档行。

    ⚠️ 这里刻意不用 `fresh_snapshot(session)`（`db_session` 自己 rollback）：
    解析线程写的是**另一个连接**，而 `db_session` 的身份映射里还留着上传时
    `create_document()` 那个对象 —— `expire_on_commit=False` + 「没有活动事务时
    rollback 不触发过期」两个条件叠在一起，`session.get()` 会**直接命中缓存
    而不发查询**，于是断言读到的是上传那一刻的 `pending`。
    实测症状：状态机那几条用例会以「明明失败了却读到 pending」的形式失败。
    """
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)
    with factory() as probe:
        return kb_repository.get_document(probe, int(doc_id))


def _chunks_of(settings, user, kb_id: int) -> int:  # noqa: ANN001, ANN202
    return kb_store.count_chunks(settings=settings, user_id=user_id_of(user), kb_id=int(kb_id))


def _raise(error: Exception):  # noqa: ANN202
    def _inner(*_args, **_kwargs):  # noqa: ANN202
        raise error

    return _inner


# -----------------------------------------------------------------------------
# 1. 上传准入：格式与体积
# -----------------------------------------------------------------------------
def test_unsupported_format_is_rejected_before_anything_is_written(db_session, user, settings) -> None:  # noqa: ANN001
    """spec：「不支持的格式必须以明确文案拒绝，且**不产生任何文档记录**」。

    两半都要断：文案要说清支持哪几种；库里不能留下一条注定失败的记录 ——
    后者会让用户以为上传成功了。
    """
    base = _base(db_session, user)

    with pytest.raises(AppError) as caught:
        _upload(db_session, user, filename="表格.xlsx", kb_id=int(base.id))

    assert caught.value.code == ErrorCode.UPLOAD_INVALID
    assert "PDF" in caught.value.message and ".md" in caught.value.message
    fresh_snapshot(db_session)
    assert kb_repository.count_documents(db_session, kb_id=int(base.id)) == 0


def test_oversized_file_is_rejected_with_the_limit_in_the_message(db_session, user, kb_env) -> None:  # noqa: ANN001
    settings = kb_env(KB_DOC_MAX_BYTES=100)
    base = _base(db_session, user)

    with pytest.raises(AppError) as caught:
        _upload(db_session, user, filename="大文件.md", content=b"x" * 200, kb_id=int(base.id))

    assert caught.value.code == ErrorCode.UPLOAD_INVALID
    assert "100" in caught.value.message or "上限" in caught.value.message
    fresh_snapshot(db_session)
    assert kb_repository.count_documents(db_session, kb_id=int(base.id)) == 0
    assert settings.kb_doc_max_bytes == 100


def test_missing_filename_is_rejected(db_session, user, settings) -> None:  # noqa: ANN001
    """spec：「没有携带可用的文件名 → 拒绝，而不是回落按 MIME 猜」。

    微信端 `Taro.uploadFile` 只会把临时路径的最后一段当 multipart filename，
    所以「文件名没了」是**真的会发生**的情况，不是假想输入。
    """
    with pytest.raises(AppError) as caught:
        _upload(db_session, user, filename="")

    assert caught.value.code == ErrorCode.UPLOAD_INVALID


def test_filename_without_extension_is_rejected(db_session, user, settings) -> None:  # noqa: ANN001
    with pytest.raises(AppError) as caught:
        _upload(db_session, user, filename="README")

    assert caught.value.code == ErrorCode.UPLOAD_INVALID


# -----------------------------------------------------------------------------
# 2. 归属：越权与不存在同形
# -----------------------------------------------------------------------------
def test_upload_into_other_users_base_is_refused(db_session, user, other_user, settings) -> None:  # noqa: ANN001
    """spec：「向他人知识库标识上传 → 请求被拒绝，且不写入任何文件或记录」。"""
    theirs = _base(db_session, other_user)

    with pytest.raises(AppError) as caught:
        _upload(db_session, user, filename="偷传.md", kb_id=int(theirs.id))

    assert caught.value.code == ErrorCode.RESOURCE_NOT_FOUND
    fresh_snapshot(db_session)
    assert kb_repository.count_documents(db_session, kb_id=int(theirs.id)) == 0


def test_upload_into_missing_base_looks_identical_to_forbidden(db_session, user, other_user, settings) -> None:  # noqa: ANN001
    """两种失败必须**逐位一致** —— 否则错误码差异就成了「这个 id 存不存在」的探针。"""
    theirs = _base(db_session, other_user)

    with pytest.raises(AppError) as forbidden:
        _upload(db_session, user, filename="a.md", kb_id=int(theirs.id))
    with pytest.raises(AppError) as missing:
        _upload(db_session, user, filename="a.md", kb_id=999_999_999)

    assert forbidden.value.code == missing.value.code
    assert forbidden.value.message == missing.value.message


def test_base_full_is_refused(db_session, user, kb_env) -> None:  # noqa: ANN001
    """文档数上限是防呆：不拦的话一次上传就能把解析池占死几分钟。"""
    kb_env(KB_MAX_DOCS_PER_BASE=1)
    base = _base(db_session, user)
    _upload(db_session, user, filename="a.md", kb_id=int(base.id))

    with pytest.raises(AppError) as caught:
        _upload(db_session, user, filename="b.md", kb_id=int(base.id))

    # 4001（输入不合规）而不是 4002：文件本身没有任何问题，是这个库满了
    assert caught.value.code == ErrorCode.INVALID_INPUT
    fresh_snapshot(db_session)
    assert kb_repository.count_documents(db_session, kb_id=int(base.id)) == 1


# -----------------------------------------------------------------------------
# 3. 上传本体：立即返回 + 落盘 + 默认库
# -----------------------------------------------------------------------------
def test_upload_returns_before_parse(db_session, user, settings) -> None:  # noqa: ANN001
    """不替换 `_submit`，让解析真的进池 —— 返回时状态**必须**还是 `pending`。

    这条锁的是「上传立即返回」：若哪次改成同步等待解析，这里会变成 `ready`。
    """
    base = _base(db_session, user)

    envelope = _upload(db_session, user, filename="讲义.md", kb_id=int(base.id))

    assert envelope.document.status == "pending"
    assert envelope.poll_interval_ms == settings.kb_doc_poll_interval_ms
    kb_service.shutdown(wait=True)


def test_upload_writes_the_original_file(db_session, user, settings) -> None:  # noqa: ANN001
    """原文件必须落在 `uploads/kb/{user}/{doc}.md`。

    保留它的理由不是「以后要下载」（本期不做），而是**解析失败后要能重试** ——
    失败时把文件删掉的话，用户唯一的出路是重新选一次文件。
    """
    base = _base(db_session, user)

    envelope = _upload(db_session, user, filename="讲义.md", kb_id=int(base.id))
    path = settings.kb_documents_path / str(user_id_of(user)) / f"{envelope.document.id}.md"

    assert path.is_file()
    assert path.read_bytes() == SHORT_TEXT.encode("utf-8")


def test_upload_without_kb_id_uses_the_default_base(db_session, user, settings) -> None:  # noqa: ANN001
    """大厅那个「上传文档」入口不知道任何库 id，所以必须有默认库接住（design D14 的同源问题）。"""
    envelope = _upload(db_session, user, filename="随手传.md")

    fresh_snapshot(db_session)
    row = kb_repository.get_base(db_session, int(envelope.document.kb_id))
    assert row is not None and row.name == KB_DEFAULT_NAME

    # 第二次上传复用同一个库，而不是又建一个
    second = _upload(db_session, user, filename="再传一份.md")
    fresh_snapshot(db_session)
    assert kb_repository.count_documents(db_session, kb_id=int(envelope.document.kb_id)) == 2
    assert int(second.document.kb_id) == int(envelope.document.kb_id)


def test_upload_reuses_the_default_base_of_that_user_only(db_session, user, other_user, settings) -> None:  # noqa: ANN001
    mine = _upload(db_session, user, filename="我的.md")
    theirs = _upload(db_session, other_user, filename="他的.md")

    assert int(mine.document.kb_id) != int(theirs.document.kb_id)


# -----------------------------------------------------------------------------
# 4. 解析成功：状态机 + 向量
# -----------------------------------------------------------------------------
def test_parse_success_marks_ready_and_writes_vectors(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    base = _base(db_session, user)

    envelope = _upload(
        db_session, user, filename="长文.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(base.id)
    )
    row = _doc_row(db_session, int(envelope.document.id))

    assert row is not None
    assert row.status == "ready"
    assert row.chunk_count > 1, "长文应该被切成多段"
    assert row.error_code == "" and row.error_message == ""
    assert row.parsed_at is not None
    assert _chunks_of(settings, user, int(base.id)) == int(row.chunk_count)


def test_parse_records_page_count_from_the_loader(db_session, user, settings, inline_parse, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001, ARG001
    """页数由加载器给出、原样落到文档上。

    用替身而不是真造一份 PDF：这里要验的是**透传**，PDF 本身的解析由
    `test_kb_loaders.py` 用真库钉着（构造器重复一遍只是增加维护面）。
    """
    base = _base(db_session, user)
    monkeypatch.setattr(
        kb_service.loaders,
        "load_document",
        lambda path, *, filename: LoadedDocument(text=SHORT_TEXT, page_count=7),
    )

    envelope = _upload(db_session, user, filename="假装是.pdf", kb_id=int(base.id))
    row = _doc_row(db_session, int(envelope.document.id))

    assert row is not None and row.page_count == 7


def test_parsing_state_is_visible_mid_flight(db_session, user, settings, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """`pending → parsing → ready` 三步都要真的经过 —— 中间态不能跳。

    造法：把加载器换成「先看一眼库里现在是什么状态、再返回」的替身。
    这一读用的是**新会话**，所以看到的是那一刻的真相，而不是解析线程手里的快照。

    这条同时守着一个更基础的东西：上传流程**必须先 `commit` 那一行**才提交解析任务 ——
    没提交的话解析线程在这一步读到的是 `missing`（另一个连接看不见未提交的插入）。
    """
    base = _base(db_session, user)
    seen: list[str] = []
    holder: dict[str, int] = {}

    def _probe(path, *, filename):  # noqa: ANN001, ANN202
        with kb_service._open_session() as probe:  # noqa: SLF001
            row = kb_repository.get_document(probe, holder["id"])
            seen.append(str(row.status) if row is not None else "missing")
        return LoadedDocument(text=SHORT_TEXT)

    monkeypatch.setattr(kb_service.loaders, "load_document", _probe)

    try:
        envelope = _upload(db_session, user, filename="探针.md", kb_id=int(base.id))
        holder["id"] = int(envelope.document.id)
        _wait_until(lambda: bool(seen), what="解析线程走到替身那里")
    finally:
        kb_service.shutdown(wait=True)

    assert seen == ["parsing"], "解析开始时状态必须已经落成 parsing"
    assert _doc_row(db_session, holder["id"]).status == "ready"  # type: ignore[union-attr]



# -----------------------------------------------------------------------------
# 5. 解析失败：可诊断、可重试、绝不假装就绪
# -----------------------------------------------------------------------------
def test_blank_document_fails_instead_of_ready_with_zero_chunks(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """spec：「解析成功但产出为空 → 判为解析失败，不写入零个片段却标记为已就绪」。

    这一条是整条链上最危险的一个静默失败：`ready` + 0 片段意味着
    界面上一切正常、出题时却一条资料都拿不到，用户会以为是自己资料的问题。
    """
    base = _base(db_session, user)

    envelope = _upload(db_session, user, filename="空白.md", content=b"   \n\t  ", kb_id=int(base.id))
    row = _doc_row(db_session, int(envelope.document.id))

    assert row is not None
    assert row.status == "failed"
    assert row.chunk_count == 0
    assert row.error_message, "失败必须留下可展示的原因"
    assert row.error_code
    assert _chunks_of(settings, user, int(base.id)) == 0


def test_broken_file_fails_with_a_user_facing_message(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """冒充成 `.docx` 的二进制：准入放行（信文件名）、解析阶段照实失败（design D11）。"""
    base = _base(db_session, user)

    envelope = _upload(
        db_session, user, filename="坏文件.docx", content=b"not a zip at all", kb_id=int(base.id)
    )
    row = _doc_row(db_session, int(envelope.document.id))

    assert row is not None and row.status == "failed"
    assert "解析" in row.error_message or "文字" in row.error_message
    # 用户看到的话里不该有堆栈或路径
    assert "Traceback" not in row.error_message
    assert str(settings.kb_documents_path) not in row.error_message


def test_parse_without_embedding_key_fails_rather_than_ready(db_session, user, settings, inline_parse, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001, ARG001
    """spec：向量化不可用时**必须**判失败，不得标成就绪而实际没有任何片段。

    造法：让 `_build_embeddings` 抛「没配 key」那个 5000（真实实现的行为）。
    """
    base = _base(db_session, user)
    monkeypatch.setattr(
        kb_service,
        "_build_embeddings",
        _raise(AppError(ErrorCode.INTERNAL_ERROR, "私有知识库还没配置向量化凭据")),
    )

    envelope = _upload(db_session, user, filename="讲义.md", kb_id=int(base.id))
    row = _doc_row(db_session, int(envelope.document.id))

    assert row is not None and row.status == "failed"
    assert row.chunk_count == 0
    assert _chunks_of(settings, user, int(base.id)) == 0


def test_embedding_upstream_error_fails_the_document(db_session, user, settings, inline_parse, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001, ARG001
    """上游抖动（鉴权失败 / 超时 / 配额）与「没配 key」走同一个出口：失败且可重试。"""
    base = _base(db_session, user)
    monkeypatch.setattr(kb_service, "_build_embeddings", _raise(EmbeddingError("status=401")))

    envelope = _upload(db_session, user, filename="讲义.md", kb_id=int(base.id))
    row = _doc_row(db_session, int(envelope.document.id))

    assert row is not None and row.status == "failed"
    assert "401" not in row.error_message, "上游报文不该出现在给用户看的文案里"


def test_failed_document_keeps_its_file_so_it_can_be_retried(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    base = _base(db_session, user)

    envelope = _upload(db_session, user, filename="空白.md", content=b"   ", kb_id=int(base.id))
    path = settings.kb_documents_path / str(user_id_of(user)) / f"{envelope.document.id}.md"

    assert _doc_row(db_session, int(envelope.document.id)).status == "failed"  # type: ignore[union-attr]
    assert path.is_file()


def test_reparse_turns_a_failed_document_into_ready(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """spec：「重新发起解析可使其回到可判定的状态」—— 重试是唯一不需要用户重传的出路。"""
    base = _base(db_session, user)
    envelope = _upload(db_session, user, filename="讲义.md", content=b"   ", kb_id=int(base.id))
    doc_id = int(envelope.document.id)
    assert _doc_row(db_session, doc_id).status == "failed"  # type: ignore[union-attr]

    # 把原文件修好（模拟「用户把文件重新导出了一遍」），再重试解析
    path = settings.kb_documents_path / str(user_id_of(user)) / f"{doc_id}.md"
    path.write_bytes(LONG_TEXT.encode("utf-8"))

    result = kb_service.reparse_document(db_session, user, doc_id)
    row = _doc_row(db_session, doc_id)

    assert result.document.id == str(doc_id)
    assert row is not None and row.status == "ready"
    assert row.chunk_count > 1
    assert _chunks_of(settings, user, int(base.id)) == int(row.chunk_count)


def test_reparse_clears_the_previous_failure_reason(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    base = _base(db_session, user)
    envelope = _upload(db_session, user, filename="讲义.md", content=b"   ", kb_id=int(base.id))
    doc_id = int(envelope.document.id)
    path = settings.kb_documents_path / str(user_id_of(user)) / f"{doc_id}.md"
    path.write_bytes(SHORT_TEXT.encode("utf-8"))

    kb_service.reparse_document(db_session, user, doc_id)
    row = _doc_row(db_session, doc_id)

    assert row is not None and row.error_message == ""


def test_reparse_of_a_missing_document_is_404(db_session, user, settings, other_user) -> None:  # noqa: ANN001
    """重试必须**自己**校验归属，不能只靠「上传时校验过」—— 文档 id 是可猜的。"""
    base = _base(db_session, other_user)
    envelope = _upload(db_session, other_user, filename="他的.md", kb_id=int(base.id))

    with pytest.raises(AppError) as caught:
        kb_service.reparse_document(db_session, user, int(envelope.document.id))

    assert caught.value.code == ErrorCode.RESOURCE_NOT_FOUND


def test_parse_pool_full_marks_the_document_failed(db_session, user, settings, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """池满**不排队**，直接判失败（design 的 Risks 第 7 条）。

    为什么不让它排队：排队会让「上传成功」这件事在用户那里挂上几分钟的不确定性，
    而解析是一次可以重试的操作 —— 说清楚比挂着强。
    """
    base = _base(db_session, user)
    monkeypatch.setattr(kb_service, "_submit", lambda fn, *, settings: False)

    envelope = _upload(db_session, user, filename="讲义.md", kb_id=int(base.id))
    fresh_snapshot(db_session)
    row = kb_repository.get_document(db_session, int(envelope.document.id))

    assert row is not None and row.status == "failed"
    assert row.error_message


# -----------------------------------------------------------------------------
# 6. 删除的连带性
# -----------------------------------------------------------------------------
def test_delete_document_removes_row_file_and_vectors(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """spec：「删除单份文档 → 记录消失，且此后检索再也命中不到它的片段」。"""
    base = _base(db_session, user)
    envelope = _upload(
        db_session, user, filename="长文.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(base.id)
    )
    doc_id = int(envelope.document.id)
    path = settings.kb_documents_path / str(user_id_of(user)) / f"{doc_id}.md"
    assert _chunks_of(settings, user, int(base.id)) > 0

    kb_service.delete_document(db_session, user, doc_id)

    fresh_snapshot(db_session)
    assert kb_repository.get_document(db_session, doc_id) is None
    assert not path.exists()
    assert _chunks_of(settings, user, int(base.id)) == 0


def test_delete_document_of_another_user_is_404(db_session, user, other_user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    base = _base(db_session, other_user)
    envelope = _upload(db_session, other_user, filename="他的.md", kb_id=int(base.id))
    doc_id = int(envelope.document.id)

    with pytest.raises(AppError) as caught:
        kb_service.delete_document(db_session, user, doc_id)

    assert caught.value.code == ErrorCode.RESOURCE_NOT_FOUND
    fresh_snapshot(db_session)
    assert kb_repository.get_document(db_session, doc_id) is not None, "别人的文档必须原封不动"


def test_delete_base_removes_documents_vectors_and_files(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """spec：「删除整个知识库 → 库的记录、其全部文档记录与全部向量一并清除」。"""
    base = _base(db_session, user)
    other = _base(db_session, user, name="另一个库")
    ids = []
    for name in ("甲", "乙"):
        envelope = _upload(
            db_session,
            user,
            filename=f"{name}.md",
            content=LONG_TEXT.encode("utf-8"),
            kb_id=int(base.id),
        )
        ids.append(int(envelope.document.id))
    _upload(
        db_session,
        user,
        filename="别的库.md",
        content=LONG_TEXT.encode("utf-8"),
        kb_id=int(other.id),
    )
    assert _chunks_of(settings, user, int(base.id)) > 0

    kb_service.delete_base(db_session, user, int(base.id))

    fresh_snapshot(db_session)
    assert kb_repository.get_base(db_session, int(base.id)) is None
    assert kb_repository.count_documents(db_session, kb_id=int(base.id)) == 0
    assert _chunks_of(settings, user, int(base.id)) == 0
    for doc_id in ids:
        assert not (settings.kb_documents_path / str(user_id_of(user)) / f"{doc_id}.md").exists()
    # 别的库一点没动
    assert kb_repository.count_documents(db_session, kb_id=int(other.id)) == 1
    assert _chunks_of(settings, user, int(other.id)) > 0


def test_delete_base_of_another_user_is_404(db_session, user, other_user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    theirs = _base(db_session, other_user)

    with pytest.raises(AppError) as caught:
        kb_service.delete_base(db_session, user, int(theirs.id))

    assert caught.value.code == ErrorCode.RESOURCE_NOT_FOUND
    fresh_snapshot(db_session)
    assert kb_repository.get_base(db_session, int(theirs.id)) is not None


def test_parsing_thread_does_not_resurrect_a_deleted_document(db_session, user, settings, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """spec：「删除解析中的文档 → 解析完成后不会再把它写回库里」。

    ⚠️ 这条最容易写漏：删掉的是数据库行，而解析线程手里还拿着文本与向量。
    若不复查就回写，症状是「删掉的内容还会出现在题目里」——
    而且库里会留下一条指向已删文档的孤儿向量，谁也说不清它是哪来的。

    造法：**不让上传去起解析**（把 `_submit` 换成「收下但不执行」），
    然后在主线程里自己调一次 `run_parse`，其中 `store.add_chunks` 被换成
    「写完向量之后立刻把文档行删掉」—— 正好模拟「用户的删除卡在回写之前」。
    跑在主线程里是刻意的：起真线程会让这条用例变成两个解析线程赛跑，
    而赛跑的失败是间歇性的（实测 3 轮里坏 2 轮）。
    """
    base = _base(db_session, user)
    monkeypatch.setattr(kb_service, "_submit", lambda fn, *, settings: True)

    envelope = _upload(db_session, user, filename="讲义.md", kb_id=int(base.id))
    doc_id = int(envelope.document.id)
    assert _doc_row(db_session, doc_id).status == "pending"  # type: ignore[union-attr]

    real_add = kb_store.add_chunks

    def add_then_delete(**kwargs):  # noqa: ANN003, ANN202
        written = real_add(**kwargs)
        with kb_service._open_session() as deleter:  # noqa: SLF001
            row = kb_repository.get_document(deleter, doc_id)
            if row is not None:
                kb_repository.delete_document(deleter, row)
        return written

    monkeypatch.setattr(kb_service.kb_store, "add_chunks", add_then_delete)

    kb_service.run_parse(doc_id, user_id=user_id_of(user))

    assert _doc_row(db_session, doc_id) is None
    assert (
        _chunks_of(settings, user, int(base.id)) == 0
    ), "解析线程发现文档已被删除时，必须把自己刚写进去的向量一并清掉"


def test_parse_of_a_missing_document_is_a_noop(db_session, user, settings) -> None:  # noqa: ANN001
    """进程重启后遗留的解析任务可能指向已经不存在的文档 —— 不能炸。"""
    kb_service.run_parse(999_999_999, user_id=user_id_of(user))


# -----------------------------------------------------------------------------
# 7. 库的读写
# -----------------------------------------------------------------------------
def test_create_base_returns_counts_and_rejects_duplicate_name(db_session, user, settings) -> None:  # noqa: ANN001
    item = _base(db_session, user, name="真题库")
    assert item.name == "真题库"
    assert item.document_count == 0 and item.ready_count == 0

    with pytest.raises(AppError) as caught:
        kb_service.create_base(db_session, user, name="真题库", description="")

    assert caught.value.code == ErrorCode.INVALID_INPUT
    fresh_snapshot(db_session)
    assert len(kb_repository.list_bases(db_session, user_id=user_id_of(user))) == 1


def test_base_detail_lists_documents_with_statuses(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """详情页（也是解析进度页轮询的接口）要一次给全：库的计数 + 每份文档的状态。"""
    base = _base(db_session, user)
    _upload(db_session, user, filename="好的.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(base.id))
    _upload(db_session, user, filename="坏的.md", content=b"   ", kb_id=int(base.id))

    detail = kb_service.base_detail(db_session, user, int(base.id))

    assert detail.base.document_count == 2
    assert detail.base.ready_count == 1
    assert [doc.filename for doc in detail.documents] == ["好的.md", "坏的.md"]
    assert [doc.status for doc in detail.documents] == ["ready", "failed"]
    assert detail.documents[1].error_message


def test_base_detail_of_another_user_is_404(db_session, user, other_user, settings) -> None:  # noqa: ANN001
    theirs = _base(db_session, other_user)

    with pytest.raises(AppError) as caught:
        kb_service.base_detail(db_session, user, int(theirs.id))

    assert caught.value.code == ErrorCode.RESOURCE_NOT_FOUND


def test_rename_base_keeps_documents(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    base = _base(db_session, user)
    _upload(db_session, user, filename="讲义.md", kb_id=int(base.id))

    item = kb_service.update_base(db_session, user, int(base.id), name="改过的名字", description="新的描述")

    assert item.name == "改过的名字" and item.description == "新的描述"
    assert item.document_count == 1


def test_rename_to_an_existing_name_is_rejected(db_session, user, settings) -> None:  # noqa: ANN001
    _base(db_session, user, name="甲库")
    second = _base(db_session, user, name="乙库")

    with pytest.raises(AppError) as caught:
        kb_service.update_base(db_session, user, int(second.id), name="甲库")

    assert caught.value.code == ErrorCode.INVALID_INPUT
    fresh_snapshot(db_session)
    assert kb_repository.get_base(db_session, int(second.id)).name == "乙库"  # type: ignore[union-attr]


def test_list_bases_counts_documents(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    base = _base(db_session, user)
    _upload(db_session, user, filename="好.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(base.id))
    _upload(db_session, user, filename="坏.md", content=b"   ", kb_id=int(base.id))

    listing = kb_service.list_bases(db_session, user)

    assert listing.total == 1
    assert listing.items[0].document_count == 2
    assert listing.items[0].ready_count == 1, "「能不能出题」看的是 ready_count"


# -----------------------------------------------------------------------------
# 8. 检索契约（出题链在 Group 8 会用它）
# -----------------------------------------------------------------------------
def test_search_returns_chunks_from_the_ready_documents(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    base = _base(db_session, user)
    _upload(db_session, user, filename="长文.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(base.id))

    outcome = kb_service.search_base(
        db_session, user_id=user_id_of(user), kb_id=int(base.id), query="监督学习"
    )

    assert outcome.reason == "ok"
    assert outcome.chunks
    assert all(chunk.kb_id == int(base.id) for chunk in outcome.chunks)
    assert all(chunk.filename == "长文.md" for chunk in outcome.chunks)


def test_search_on_a_base_without_ready_documents_is_distinguishable(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """spec：「指定的知识库只有解析中或解析失败的文档 → 返回空结果，
    且系统能区分「库是空的」与「检索没命中」」。

    区分它的用处是**给用户的一句话**：空库应该提示「这个库还没有可用的资料」，
    而没命中只能说「这次没找到相关内容」。
    """
    base = _base(db_session, user)
    _upload(db_session, user, filename="坏的.md", content=b"   ", kb_id=int(base.id))

    outcome = kb_service.search_base(
        db_session, user_id=user_id_of(user), kb_id=int(base.id), query="监督学习"
    )

    assert outcome.reason == "empty_base"
    assert outcome.chunks == []


def test_search_reports_no_hit_when_vectors_are_missing(db_session, user, settings) -> None:  # noqa: ANN001
    """库里标着 `ready` 却没有向量（数据不一致）→ `no_hit`，而不是假装空库。

    这种不一致在正常路径上不该出现，但真出现时（比如向量库被手工清过），
    报「空库」会把排查引向错误的方向。
    """
    base = _base(db_session, user)
    doc = kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="幽灵.md", ext="md", size_bytes=1
    )
    kb_repository.mark_ready(db_session, doc, chunk_count=3)
    db_session.commit()

    outcome = kb_service.search_base(
        db_session, user_id=user_id_of(user), kb_id=int(base.id), query="监督学习"
    )

    assert outcome.reason == "no_hit"


def test_search_never_raises_when_the_vector_store_is_down(db_session, user, settings, inline_parse, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001, ARG001
    """spec：「检索时向量库不可用 → 记为失败，出题继续进行」。

    所以这一层**只返回 reason**，不抛异常 —— 把「检索挂了」升级成「整次出题失败」
    是把一次降级变成一次损失。
    """
    base = _base(db_session, user)
    _upload(db_session, user, filename="长文.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(base.id))
    monkeypatch.setattr(kb_service.kb_store, "search_chunks", _raise(RuntimeError("chroma is down")))

    outcome = kb_service.search_base(
        db_session, user_id=user_id_of(user), kb_id=int(base.id), query="监督学习"
    )

    assert outcome.reason == "failed"
    assert outcome.chunks == []


def test_search_does_not_cross_libraries(db_session, user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """两个库都要有内容，才谈得上「没有串库」。"""
    first = _base(db_session, user, name="甲库")
    second = _base(db_session, user, name="乙库")
    _upload(db_session, user, filename="甲料.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(first.id))
    _upload(db_session, user, filename="乙料.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(second.id))

    outcome = kb_service.search_base(
        db_session, user_id=user_id_of(user), kb_id=int(first.id), query="监督学习"
    )

    assert {chunk.filename for chunk in outcome.chunks} == {"甲料.md"}


def test_search_does_not_cross_users(db_session, user, other_user, settings, inline_parse) -> None:  # noqa: ANN001, ARG001
    """`kb_id` 是全局自增的，别人库里同号的片段绝不能出现在我的检索里。"""
    mine = _base(db_session, user)
    theirs = _base(db_session, other_user)
    _upload(db_session, user, filename="我的.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(mine.id))
    _upload(
        db_session, other_user, filename="他的.md", content=LONG_TEXT.encode("utf-8"), kb_id=int(theirs.id)
    )

    outcome = kb_service.search_base(
        db_session, user_id=user_id_of(user), kb_id=int(theirs.id), query="监督学习"
    )

    assert all(chunk.filename != "他的.md" for chunk in outcome.chunks)
