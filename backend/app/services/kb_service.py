"""私有知识库的服务层：准入 → 落盘 → 后台解析 → 状态迁移 → 连带清理。

## 两条职责链

| 调用方 | 场景 | 事务 |
|---|---|---|
| 接口层（请求线程） | 上传、改名、删除、查列表 | 由 `get_db` 的会话承担 |
| 解析线程（后台） | 解析与状态回写 | **自己开短事务**（`_open_session`），见下 |

解析线程刻意**不持有长事务**：解析一份长文档要十几秒（含向量化），
中间握着一条数据库连接既没意义（那段时间不读也不写库）又会占住连接池。
所以它按「认领 → 计算 → 回写」切成两三个短事务 —— 且这一段有个额外好处：
**回写时拿到的是新快照**，于是「解析期间用户把文档删了」这件事能被看见
（同一事务内是 REPEATABLE READ，用什么办法都读不到别人的 DELETE）。

## 失败一律落到文档状态上，不往上抛

`run_parse()` 跑在裸线程里，抛出去只会静默消失，任务永远停在「解析中」。
所以它把每一类失败都翻译成 `failed` + 一个 `error_code` 与一句可展示的话：

| error_code | 触发 | 给用户的话 |
|---|---|---|
| `parse_failed` | 加载器/分块失败（加密、坏文件、抽取为空） | 加载器自己写好的那句 |
| `unsupported_format` | 扩展名在解析时不被支持（准入已拦，属兜底） | 同上 |
| `embedding_unavailable` | 未配凭据、鉴权失败、超时、配额 | 「知识库服务暂时不可用，请稍后再试」 |
| `store_failed` | 向量库写入失败 | 同上 |
| `pool_busy` | 解析池满（不排队） | 「系统有点忙，请稍后重试」 |
| `source_missing` | 重试时原文件已不在盘上 | 「原文件已不存在，请重新上传这份资料」 |
| `internal` | 其它 | 「这份文件没能解析成功，请稍后重试」 |

**加载器的文案直接给用户看**（它是我们逐条写过的、面向人的句子），
而上游异常（`EmbeddingError` / 任何第三方异常）一律换成通用句 ——
上游报文进界面既帮不了用户，又可能带出内部信息（spec 明确要求两者分开存放）。

## 删除的顺序：先删记录，再清向量与文件

记录是真相。先删记录，则「解析线程看到文档不在了就放弃回写」这条保护立刻生效；
反过来先清向量的话，中间那一小段时间里文档仍然可检索，而且用户看到的
是「删了但还在」。清向量/清文件失败只记日志、不报错 —— 记录已经删掉了，
此时抛 500 只会让用户以为没删成功而反复操作。

## 上传流程里那个必须存在的 `commit`

`_submit()` 之前**必须** `commit()`：解析线程用另一个连接读那一行，
读不到就会安静地什么都不做（见 `kb_tasks` 模块头）。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.embeddings import Embeddings
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AppError,
    ErrorCode,
    invalid_input,
    resource_not_found,
    upload_invalid,
)
from app.core.logging import get_logger
from app.db.session import session_scope
from app.db.tables import KnowledgeBase, KnowledgeDocument, User
from app.llm.kb import loaders, splitter
from app.llm.kb import store as kb_store
from app.llm.kb.embedding import EmbeddingError, build_embeddings
from app.llm.kb.loaders import DocumentParseError, UnsupportedFormatError
from app.llm.kb.store import KbChunk
from app.models.kb import (
    KbBaseDeleteResponse,
    KbBaseDetailResponse,
    KbBaseItem,
    KbDocumentDeleteResponse,
    KbDocumentEnvelope,
    KbDocumentItem,
    KbListResponse,
)
from app.services import kb_repository, kb_tasks

logger = get_logger(__name__)

#: 准入文案里那份支持清单。写在一处：它同时是「被拒时给用户看的话」与
#: 「前端选择器该放哪些格式」的源头（前端拿不到它，所以那一份在 copy.ts 里）。
_FORMAT_HINT = "PDF、Word（.docx）、Markdown（.md）与纯文本（.txt）"

#: 这些是给用户看的句子（不掺上游报文）。
_EMBEDDING_UNAVAILABLE = "知识库服务暂时不可用，请稍后再试"
_POOL_BUSY = "系统有点忙，请稍后重试"
_PARSE_FALLBACK = "这份文件没能解析成功，请稍后重试"
_SOURCE_MISSING = "原文件已不存在，请重新上传这份资料"

#: 落库文件名（`knowledge_documents.filename VARCHAR(255)`）的显示上限。
#: 从**尾部**截：扩展名在尾部，截头会让一份好文件变成「不支持的格式」。
_FILENAME_MAX = 255

# -----------------------------------------------------------------------------
# 可替换的接缝（与 `quiz_service` 同一套写法：模块级、显式、测试可注入）
# -----------------------------------------------------------------------------
#: 后台线程开会话的方式。测试必须把它指向测试库，否则解析会往业务库写。
_open_session: Callable[[], AbstractContextManager[Session]] = session_scope

#: 解析任务提交入口。返回 `False` 表示池满（调用方把文档判失败）。
def _submit(fn: Callable[[], None], *, settings: Settings) -> bool:
    return kb_tasks.submit(fn, workers=int(settings.kb_parse_workers))


#: 向量化器工厂。测试注入确定性假实现（红线：测试不发真实 LLM 请求）。
_build_embeddings: Callable[[Settings], Embeddings] = build_embeddings


def shutdown(wait: bool = False) -> None:
    """关掉解析池（进程退出 / 测试收尾）。"""
    kb_tasks.shutdown(wait=wait)


# -----------------------------------------------------------------------------
# 内部小工具
# -----------------------------------------------------------------------------
def _document_path(settings: Settings, user_id: int, doc_id: int, ext: str) -> Path:
    """原文件的落盘路径。

    `ext` 库里存的是**不带点**的形式（与列注释一致），补点只发生在这一处。
    按 `user_id` 再分一层：一个用户的文档不至于几千个挤在同一个目录里，
    删库时也只需 `rmdir` 一个可能变空的子目录。
    """
    return settings.kb_documents_path / str(int(user_id)) / f"{int(doc_id)}.{ext}"


def _size_hint(max_bytes: int) -> str:
    """把字节上限说成用户看得懂的单位（20 MB / 500 KB）。"""
    if max_bytes % (1024 * 1024) == 0:
        return f"{max_bytes // (1024 * 1024)} MB"
    return f"{max(1, max_bytes // 1024)} KB"


def _clip_filename(name: str) -> str:
    return name[-_FILENAME_MAX:] if len(name) > _FILENAME_MAX else name


def _document_item(row: KnowledgeDocument) -> KbDocumentItem:
    return KbDocumentItem(
        id=str(row.id),
        kb_id=str(row.kb_id),
        filename=row.filename,
        ext=row.ext,
        size_bytes=int(row.size_bytes),
        status=row.status,  # type: ignore[arg-type] - 闭集由数据库写入侧保证
        chunk_count=int(row.chunk_count),
        page_count=int(row.page_count),
        error_message=row.error_message or "",
        created_at=row.created_at,
        parsed_at=row.parsed_at,
    )


def _base_item(session: Session, row: KnowledgeBase) -> KbBaseItem:
    """库 + 两个计数。

    ⚠️ 每个库两条 `COUNT` 查询。库的数量是「个位数」量级（原型 05·5 的列表
    就是一屏），所以不做聚合优化 —— 真要优化时该一次 `GROUP BY` 把全部库
    的计数取回来，而不是把文档列表整份拉给前端去数。
    """
    return KbBaseItem(
        id=str(row.id),
        name=row.name,
        description=row.description or "",
        document_count=kb_repository.count_documents(session, kb_id=int(row.id)),
        ready_count=kb_repository.count_ready_documents(session, kb_id=int(row.id)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _envelope(settings: Settings, row: KnowledgeDocument) -> KbDocumentEnvelope:
    return KbDocumentEnvelope(
        document=_document_item(row),
        poll_interval_ms=int(settings.kb_doc_poll_interval_ms),
    )


def require_owned_base(session: Session, *, user_id: int, kb_id: int) -> KnowledgeBase:
    """校验「这个库属于这个用户」，返回那一行。**越权与不存在返回同一个 4005。**

    这是全项目**唯一**的库归属判定实现点。做成公开函数是因为出题链也要用它
    （design D13：`kb_id` 在**建任务之前**就要校验），而那条路径上只有
    `user_id`，没有 `User` 对象 —— 它不该为了拿一个 id 去把用户查出来。

    Args:
        session: 请求级会话。**由调用方显式传入** —— 服务层不自己开会话，
            否则测试无从注入（见 `quiz_service` 模块头那条约定）。
        user_id: 归属判据。来自鉴权，**绝不来自请求体**。
        kb_id: 目标库。

    Raises:
        AppError: 4005（库不存在，或存在但不属于该用户）。
    """
    row = kb_repository.get_base(session, int(kb_id), user_id=int(user_id))
    if row is None:
        raise resource_not_found(detail=f"kb_id={kb_id} user_id={user_id}")
    return row


def _own_base(session: Session, user: User, kb_id: int) -> KnowledgeBase:
    """取库并校验归属。**越权与不存在返回同一个 4005**（spec 的硬要求）。"""
    return require_owned_base(session, user_id=int(user.id), kb_id=kb_id)


def _own_document(session: Session, user: User, doc_id: int) -> KnowledgeDocument:
    row = kb_repository.get_document(session, int(doc_id), user_id=int(user.id))
    if row is None:
        raise resource_not_found(detail=f"doc_id={doc_id} user_id={user.id}")
    return row


# -----------------------------------------------------------------------------
# 库
# -----------------------------------------------------------------------------
def create_base(session: Session, user: User, *, name: str, description: str = "") -> KbBaseItem:
    """建库。

    Raises:
        AppError: 4001（该用户下已有同名库）。**不返回既有那一个** ——
            用户明确说了「新建」，回一份别的东西会让他以为名字被改了。
            （默认库那条路走的是 `get_or_create_default_base`，语义不同。）
    """
    try:
        row = kb_repository.create_base(
            session, user_id=int(user.id), name=name.strip(), description=description
        )
    except IntegrityError as exc:
        session.rollback()
        raise invalid_input("已经有同名的知识库了，换一个名字吧", detail=repr(exc)) from exc
    session.commit()
    return _base_item(session, row)


def list_bases(session: Session, user: User) -> KbListResponse:
    """本人的全部知识库（新建的在前），带文档数与会话数。"""
    rows = kb_repository.list_bases(session, user_id=int(user.id))
    items = [_base_item(session, row) for row in rows]
    return KbListResponse(total=len(items), items=items)


def base_detail(session: Session, user: User, kb_id: int) -> KbBaseDetailResponse:
    """库 + 它的全部文档。解析进度页轮询的就是它。"""
    row = _own_base(session, user, kb_id)
    documents = kb_repository.list_documents(session, kb_id=int(row.id))
    return KbBaseDetailResponse(
        base=_base_item(session, row),
        documents=[_document_item(doc) for doc in documents],
    )


def update_base(
    session: Session,
    user: User,
    kb_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> KbBaseItem:
    """改名 / 改描述（至少给一个，由请求契约保证）。"""
    row = _own_base(session, user, kb_id)
    try:
        kb_repository.update_base(
            session,
            row,
            name=name.strip() if name is not None else None,
            description=description,
        )
    except IntegrityError as exc:
        session.rollback()
        raise invalid_input("已经有同名的知识库了，换一个名字吧", detail=repr(exc)) from exc
    session.commit()
    return _base_item(session, row)


def delete_base(
    session: Session, user: User, kb_id: int, *, settings: Settings | None = None
) -> KbBaseDeleteResponse:
    """删库：库记录 + 全部文档记录 + 全部向量 + 全部原文件。"""
    s = settings or get_settings()
    row = _own_base(session, user, kb_id)
    user_id = int(row.user_id)
    # 先把「要清哪些文件」问出来 —— 记录一删就问不到了
    documents = kb_repository.document_paths(session, kb_id=int(row.id))

    kb_repository.delete_base(session, row)  # 文档行由外键 CASCADE 一起走
    session.commit()

    _purge_vectors(settings=s, user_id=user_id, kb_id=int(kb_id))
    for doc_id, ext in documents:
        _remove_file(_document_path(s, user_id, doc_id, ext))
    _remove_dir_if_empty(s.kb_documents_path / str(user_id))

    return KbBaseDeleteResponse(kb_id=str(kb_id))


# -----------------------------------------------------------------------------
# 文档
# -----------------------------------------------------------------------------
def upload_document(
    session: Session,
    user: User,
    *,
    filename: str,
    data: bytes,
    kb_id: int | str | None = None,
    settings: Settings | None = None,
) -> KbDocumentEnvelope:
    """接收一份文档：准入 → 落盘 → 建记录 → 交给解析池。

    `kb_id` 不传时落进**默认库**（没有就建）—— 大厅那个「上传文档」入口
    并不知道任何库 id，而原型的「新建知识库」是独立一屏、本期不做。

    Raises:
        AppError: 4005 库不存在 / 不属于当前用户；4002 格式或体积不合规；
            4001 该库文档数已满；5000 原文件写盘失败。
    """
    s = settings or get_settings()
    user_id = int(user.id)

    base = (
        kb_repository.get_or_create_default_base(session, user_id=user_id)
        if kb_id is None
        else _own_base(session, user, int(kb_id))
    )

    name = (filename or "").strip()
    if not name:
        # spec：「文件名缺失或非法 → 拒绝，而不是回落按 MIME 类型猜测」
        raise upload_invalid("没能拿到文件名，请重新选择文件")
    if not loaders.is_supported_ext(name):
        raise upload_invalid(f"只支持 {_FORMAT_HINT} 这几种格式，请换一个文件")
    if len(data) > int(s.kb_doc_max_bytes):
        raise upload_invalid(
            f"文件太大了（上限 {_size_hint(int(s.kb_doc_max_bytes))}），请换一份小一点的"
        )

    limit = int(s.kb_max_docs_per_base)
    if kb_repository.count_documents(session, kb_id=int(base.id)) >= limit:
        # 4001 而不是 4002：文件本身没问题，是这个库满了
        raise invalid_input(f"这个知识库的文档数已到上限（{limit} 份），先整理一下再上传")

    ext = loaders.ext_of(name).lstrip(".")
    row = kb_repository.create_document(
        session,
        kb_id=int(base.id),
        user_id=user_id,
        filename=_clip_filename(name),
        ext=ext,
        size_bytes=len(data),
    )
    path = _document_path(s, user_id, int(row.id), ext)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        # 回滚把那条记录一起撤掉：一份「记录在、文件不在」的文档只会在
        # 解析阶段变成一句没人看得懂的失败原因。
        session.rollback()
        logger.exception("知识库原文件写盘失败：user=%s doc=%s", user_id, row.id)
        raise AppError(
            ErrorCode.INTERNAL_ERROR, "文件保存失败，请重试", detail=repr(exc)
        ) from exc

    # ⚠️ 必须先提交再提交解析任务（见模块头）
    session.commit()
    _dispatch_parse(session, row, settings=s, user_id=user_id)
    return _envelope(s, row)


def reparse_document(
    session: Session,
    user: User,
    doc_id: int,
    *,
    settings: Settings | None = None,
) -> KbDocumentEnvelope:
    """重新解析一份文档。

    它是**唯一**的恢复手段（spec：「重新发起解析可使其回到可判定的状态」）：
    进程重启后遗留的「解析中」、上游抖动导致的失败、以及用户把文件改好之后的重试，
    都靠这一条路。所以**不限制当前状态** —— 包括「正在解析中」（那个状态可能
    是上一个进程留下的墓碑，拒绝它会让人永远出不来）。
    """
    s = settings or get_settings()
    row = _own_document(session, user, doc_id)

    path = _document_path(s, int(row.user_id), int(row.id), row.ext)
    if not path.is_file():
        # 重试注定失败，就别让它跑一遍再报一个含糊的错。如实说清「得重传」。
        kb_repository.mark_failed(session, row, code="source_missing", message=_SOURCE_MISSING)
        session.commit()
        return _envelope(s, row)

    # 立刻置成「解析中」：重试是用户的一次明确动作，界面该马上有反应，
    # 而不是先退回「等待解析」再等几百毫秒。
    kb_repository.mark_parsing(session, row)
    session.commit()
    _dispatch_parse(session, row, settings=s, user_id=int(row.user_id))
    return _envelope(s, row)


def delete_document(
    session: Session,
    user: User,
    doc_id: int,
    *,
    settings: Settings | None = None,
) -> KbDocumentDeleteResponse:
    """删一份文档：记录 + 向量 + 原文件。

    spec：「删除后该文档的记录消失，且此后检索再也命中不到它的片段」。
    """
    s = settings or get_settings()
    row = _own_document(session, user, doc_id)
    user_id = int(row.user_id)
    kb_id = int(row.kb_id)
    ext = row.ext

    kb_repository.delete_document(session, row)
    session.commit()

    _purge_vectors(settings=s, user_id=user_id, doc_id=int(doc_id))
    _remove_file(_document_path(s, user_id, int(doc_id), ext))
    _remove_dir_if_empty(s.kb_documents_path / str(user_id))

    return KbDocumentDeleteResponse(doc_id=str(doc_id), kb_id=str(kb_id))


def _dispatch_parse(
    session: Session, row: KnowledgeDocument, *, settings: Settings, user_id: int
) -> None:
    """把解析任务交给后台池；池满时**就地**把文档判为失败。

    池满不是异常情况：解析池固定小规模（默认 2）且不排队。与其让用户挂着等，
    不如明确说「稍后重试」—— 原文件还在盘上，重试是一次点击的事。
    """
    doc_id = int(row.id)

    if _submit(lambda: run_parse(doc_id, user_id=user_id, settings=settings), settings=settings):
        return

    kb_repository.mark_failed(session, row, code="pool_busy", message=_POOL_BUSY)
    session.commit()


# -----------------------------------------------------------------------------
# 后台解析
# -----------------------------------------------------------------------------
def run_parse(doc_id: int, *, user_id: int, settings: Settings | None = None) -> None:
    """解析一份文档并把状态推到终态。**不抛异常**（跑在裸线程里，抛出会静默消失）。

    流程刻意切成三个短事务（理由见模块头）：
    认领（置 `parsing`）→ 纯计算（解析 / 分块 / 向量化）→ 复查并回写（置 `ready`）。
    """
    s = settings or get_settings()

    # ---- 1. 认领 ----
    with _open_session() as session:
        row = kb_repository.get_document(session, int(doc_id), user_id=int(user_id))
        if row is None:
            logger.info("解析任务放弃：文档 %s 已不存在", doc_id)
            return
        filename, ext = row.filename, row.ext
        kb_id = int(row.kb_id)
        kb_repository.mark_parsing(session, row)

    # ---- 2. 读文件、分块 ----
    try:
        loaded = loaders.load_document(_document_path(s, user_id, int(doc_id), ext), filename=filename)
        chunks = splitter.split_text(loaded.text, settings=s)
        if not chunks:
            # 走到这里说明文本非空却切不出片段（极端输入）。判失败而不是
            # 「就绪但 0 片段」—— 后者会让用户以为资料已备好（spec 明令禁止）。
            raise DocumentParseError("这份文件没能切分出可检索的片段")
    except UnsupportedFormatError as exc:
        _fail(doc_id, user_id, code="unsupported_format", message=str(exc))
        return
    except DocumentParseError as exc:
        _fail(doc_id, user_id, code="parse_failed", message=str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - 解析库的异常类型多且随版本变
        logger.exception("知识库解析出现未预期异常：doc=%s", doc_id)
        _fail(doc_id, user_id, code="parse_failed", message=_PARSE_FALLBACK, detail=repr(exc))
        return

    # ---- 3. 向量化并写入 ----
    try:
        embeddings = _build_embeddings(s)
        written = kb_store.add_chunks(
            settings=s,
            embeddings=embeddings,
            user_id=int(user_id),
            kb_id=kb_id,
            doc_id=int(doc_id),
            filename=filename,
            chunks=chunks,
        )
    except (AppError, EmbeddingError) as exc:
        # 没配凭据 / 鉴权失败 / 超时 / 配额 —— 都是「服务侧不可用」，同一句话
        _fail(doc_id, user_id, code="embedding_unavailable", message=_EMBEDDING_UNAVAILABLE, detail=repr(exc))
        return
    except Exception as exc:  # noqa: BLE001 - Chroma / 磁盘等
        logger.exception("知识库写入向量失败：doc=%s", doc_id)
        _fail(doc_id, user_id, code="store_failed", message=_EMBEDDING_UNAVAILABLE, detail=repr(exc))
        return

    # ---- 4. 复查并回写（新事务 = 新快照，才看得见「解析期间被删了」）----
    with _open_session() as session:
        row = kb_repository.get_document(session, int(doc_id), user_id=int(user_id))
        if row is None:
            # 用户在这次解析期间删掉了文档。刚写进去的向量必须自己清掉 ——
            # 不清的话库里留下一批指向已删文档的孤儿向量，症状是
            # 「删掉的内容还会出现在题目里」，而且谁也说不清它是哪来的。
            _purge_vectors(settings=s, user_id=int(user_id), doc_id=int(doc_id))
            logger.info("文档 %s 在解析期间被删除，已清掉本次写入的向量", doc_id)
            return
        kb_repository.mark_ready(
            session, row, chunk_count=written, page_count=int(loaded.page_count or 0)
        )
    logger.info("知识库解析完成：doc=%s chunks=%s", doc_id, written)


def _fail(
    doc_id: int, user_id: int, *, code: str, message: str, detail: str | None = None
) -> None:
    """把文档置为失败。

    文档已经不存在（用户删了）时安静返回：那时既没有人需要看这个状态，
    也不该再写回任何东西。
    """
    if detail:
        logger.warning("知识库解析失败：doc=%s code=%s detail=%s", doc_id, code, detail)
    else:
        logger.warning("知识库解析失败：doc=%s code=%s message=%s", doc_id, code, message)
    with _open_session() as session:
        row = kb_repository.get_document(session, int(doc_id), user_id=int(user_id))
        if row is None:
            return
        kb_repository.mark_failed(session, row, code=code, message=message)


# -----------------------------------------------------------------------------
# 向量与文件的清理（失败只记日志，不往上抛）
# -----------------------------------------------------------------------------
def _purge_vectors(
    *, settings: Settings, user_id: int, kb_id: int | None = None, doc_id: int | None = None
) -> None:
    """清向量。

    ⚠️ **不往上抛**：调用它的两条路（删文档 / 删库）都已经把记录删掉了，
    此时报 500 只会让用户以为「没删成功」而反复操作。
    失败留一条 error 日志 —— 残留向量是一个必须能被人为发现的状态，
    因为它的症状（删掉的内容还能被检索到）不指向任何报错。
    """
    try:
        if doc_id is not None:
            kb_store.delete_document(settings=settings, user_id=int(user_id), doc_id=int(doc_id))
        elif kb_id is not None:
            kb_store.delete_base(settings=settings, user_id=int(user_id), kb_id=int(kb_id))
    except Exception:  # noqa: BLE001
        logger.exception(
            "清理向量失败（会残留可检索的孤儿片段）：user=%s kb=%s doc=%s", user_id, kb_id, doc_id
        )


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("删除原文件失败（不影响已完成的删除）：%s", path)


def _remove_dir_if_empty(path: Path) -> None:
    """目录空了就摘掉。

    ⚠️ 用 `rmdir` 而不是 `rmtree`：这个目录装的是**该用户所有库**的文件，
    `rmtree` 会把别的库的原始资料一起抹掉。
    """
    try:
        os.rmdir(path)
    except OSError:
        # 非空（还有别的库的文件）或不存在 —— 两种都是正常情况
        pass


# -----------------------------------------------------------------------------
# 检索（取材料链在 Group 8 接进 Agent 循环）
# -----------------------------------------------------------------------------
#: 检索结果的三态 + 失败，回答「为什么没有内容」。
#: 它与「有内容」分开，是为了让上层的提示能说对话：
#: 空库该说「这个库还没有可用的资料」，而没命中只能说「这次没找到相关内容」。
KB_SEARCH_OK = "ok"
KB_SEARCH_EMPTY_BASE = "empty_base"
KB_SEARCH_NO_HIT = "no_hit"
KB_SEARCH_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class KbSearchOutcome:
    """一次知识库检索的结果。

    Attributes:
        chunks: 命中的片段（失败或没命中时是空列表）。
        reason: `ok` / `empty_base` / `no_hit` / `failed`。
    """

    chunks: list[KbChunk] = field(default_factory=list)
    reason: str = KB_SEARCH_NO_HIT


def search_base(
    session: Session,
    *,
    user_id: int,
    kb_id: int,
    query: str,
    settings: Settings | None = None,
    embeddings: Embeddings | None = None,
) -> KbSearchOutcome:
    """在指定库里检索。**本层是知识库检索的唯一入口**（隔离过滤在 `store` 里）。

    永远不抛异常：spec 要求「检索失败按『本次没有资料』处理，继续用其余依据出题」。
    把一次降级（少一份资料）升级成一次损失（整次出题失败）是明确被否掉的做法，
    所以这里把异常吞掉并返回 `failed` —— 并且**如实**返回 `failed`，
    绝不用任何伪造的命中凑数。

    Args:
        embeddings: 注入向量化器（测试用）；不传则按配置构造。
    """
    s = settings or get_settings()
    try:
        # 先问「这个库有没有已就绪的文档」：非 ready 的文档一条向量都没有，
        # 直接去检索只会得到一个空结果，而那与「空库」是两回事。
        if kb_repository.count_ready_documents(session, kb_id=int(kb_id)) <= 0:
            return KbSearchOutcome([], KB_SEARCH_EMPTY_BASE)
        vectors = embeddings if embeddings is not None else _build_embeddings(s)
        chunks = kb_store.search_chunks(
            settings=s,
            embeddings=vectors,
            user_id=int(user_id),
            kb_id=int(kb_id),
            query=query,
        )
    except Exception as exc:  # noqa: BLE001 - 见 docstring：降级而不是失败
        logger.warning("知识库检索失败（按「本次没有资料」处理）：user=%s kb=%s error=%r", user_id, kb_id, exc)
        return KbSearchOutcome([], KB_SEARCH_FAILED)

    return KbSearchOutcome(chunks, KB_SEARCH_OK if chunks else KB_SEARCH_NO_HIT)


def search_for_tool(
    *, user_id: int, kb_id: int, query: str, settings: Settings | None = None
) -> KbSearchOutcome:
    """**取材链专用的检索入口**：自己开一个会话。

    `search_base()` 要求调用方传 session（服务层的统一约定），但取材链不持有
    请求级会话 —— 它跑在**后台出题线程**里，那个线程只有 `_open_session` 这个接缝
    （与 `run_parse` 同一条理由）。

    为什么不让 `llm/kb/tools.py` 自己 import `_open_session`：那是个下划线开头的
    内部接缝，一旦外部模块也依赖它，「换掉会话工厂」这件事就有了两个必须同步的
    改动点 —— 而漏掉其中一个的症状是**接口测试静默地往业务库写数据**，
    这正是 `conftest` 里反复警告的那类问题（见 `db_scope` 的 docstring）。
    所以「谁开会话」这个决定留在本模块，工具只调这一个函数。
    """
    with _open_session() as session:
        return search_base(
            session, user_id=int(user_id), kb_id=int(kb_id), query=query, settings=settings
        )

