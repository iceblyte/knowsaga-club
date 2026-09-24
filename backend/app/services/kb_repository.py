"""知识库与文档的落库 / 取回。

## 为什么单独一层（同 `quiz_repository` 的理由）

`kb_service` 负责的是**流程**（准入 → 落盘 → 起解析线程 → 状态迁移 → 连带清理），
本文件负责的是**这两份数据怎么存、怎么读**。混在一起之后，改一句失败文案
要在「状态字段」和「线程池」之间来回跳，很容易顺手改错一处。

## 「不是你的」与「不存在」在这里就被合并成 `None`

`get_base()` / `get_document()` 传 `user_id` 时，**归属不符与行不存在返回同一个
`None`**。这不是偷懒：spec 要求「越权访问与不存在必须返回同一个结果」，
而把两者合并成 `None` 是最不容易写漏的实现方式 —— 只要有一个查询忘了带
归属条件，它就会返回一行，接口层的 4005 也就无从谈起。
服务层拿到 `None` 一律翻成 4005（`resource_not_found()`）。

## 事务由调用方拥有

本文件的函数**不 `commit`**，只 `flush`（需要拿到自增 id 时）。
唯一的例外是 `get_or_create_default_base()`，它用一次嵌套事务（SAVEPOINT）
把「撞唯一键」这个并发窗口收在自己内部。

## `ext` 一律不带点

列注释写的是 `pdf / docx / md / txt`，所以库里存 `md` 而不是 `.md`；
落盘路径拼接时才补点（`{doc_id}.md`）。转换只发生在 `kb_service._document_path()`
一处 —— 两处各剥/补一次迟早会漂。

## 库名的比较交给排序规则

`find_base_by_name()` 用 `==` 而不是 `func.lower(...)`：唯一键 `uk_kb_user_name`
在 MySQL 默认排序规则（`utf8mb4_*_ci`）下是**大小写不敏感**的，
所以「查得到」必须与「插得进」同真同假。真要自己写 `lower()`，
就得保证两边口径一致 —— 直接交给同一套排序规则最省事。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import KB_DEFAULT_NAME
from app.db.tables import KnowledgeBase, KnowledgeDocument
from app.utils.timeutil import utcnow

#: 文档的四个状态（spec「解析状态是显式状态机」）。
#: 计数接口按它给全量键，缺的补 0 —— 调用方不必自己 `get(key, 0)`。
DOC_STATUSES: tuple[str, ...] = ("pending", "parsing", "ready", "failed")


# -----------------------------------------------------------------------------
# 库
# -----------------------------------------------------------------------------
def create_base(
    session: Session, *, user_id: int, name: str, description: str = ""
) -> KnowledgeBase:
    """建一个知识库并 `flush`（拿到自增 id）。

    Raises:
        IntegrityError: 该用户下已有同名库。**不在这里翻译成业务错误** ——
            那是服务层的事（它才知道该给 4001 还是「取用已有那一个」）。
    """
    row = KnowledgeBase(user_id=int(user_id), name=name, description=description)
    session.add(row)
    session.flush()
    return row


def find_base_by_name(session: Session, *, user_id: int, name: str) -> KnowledgeBase | None:
    """按库名找（限本人）。默认库的 find-or-create 靠它。"""
    return session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == int(user_id), KnowledgeBase.name == name
        )
    )


def get_or_create_default_base(
    session: Session, *, user_id: int, name: str = KB_DEFAULT_NAME
) -> KnowledgeBase:
    """取用户的默认库；没有就建一个。

    原型的「新建知识库」是独立一屏，本期不做 —— 所以「上传时库里还没有库」
    这个情况必须有地方接住：接住它的就是这里。库名事后可以在详情页改。

    ⚠️ **并发窗口是真实存在的**：同一个用户连点两次上传，两次请求都会走到
    「查不到 → 插入」。所以插入包在嵌套事务里，撞到唯一键就回滚这一次插入、
    重查一遍取用对方刚建好的那一行。若不用 SAVEPOINT，`IntegrityError` 会把
    整个事务标成不可用，后面连查询都做不了，用户看到的是一个 500。
    """
    existing = find_base_by_name(session, user_id=user_id, name=name)
    if existing is not None:
        return existing

    try:
        with session.begin_nested():
            return create_base(session, user_id=user_id, name=name)
    except IntegrityError:
        row = find_base_by_name(session, user_id=user_id, name=name)
        if row is None:
            # 撞了唯一键却查不到 —— 说明唯一键约束的语义与这里的查询不一致
            # （比如以后有人换了排序规则）。宁可抛出，也不要静默建出重复的库。
            raise
        return row


def get_base(session: Session, kb_id: int, *, user_id: int | None = None) -> KnowledgeBase | None:
    """按 id 取库；传 `user_id` 时同时校验归属（不属于则返回 `None`）。"""
    row = session.get(KnowledgeBase, int(kb_id))
    if row is None:
        return None
    if user_id is not None and int(row.user_id) != int(user_id):
        return None
    return row


def list_bases(session: Session, *, user_id: int) -> list[KnowledgeBase]:
    """列本人的全部库，**新建的在前**。

    排序按 `created_at` 再按 `id`：同一秒内建的两个库（接口测试里很常见）
    若只按时间排，返回顺序就是不确定的，而「列表顺序随机」会让截图对账失效。
    """
    return list(
        session.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.user_id == int(user_id))
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
        ).all()
    )


def update_base(
    session: Session,
    row: KnowledgeBase,
    *,
    name: str | None = None,
    description: str | None = None,
) -> KnowledgeBase:
    """改名 / 改描述。`None` 表示「这一项不动」——**空串是有效值**（把描述清空）。"""
    if name is not None:
        row.name = name
    if description is not None:
        row.description = description
    row.updated_at = utcnow()
    session.flush()
    return row


def delete_base(session: Session, row: KnowledgeBase) -> None:
    """删库（**只删数据库行**）。

    它的文档由外键 `ON DELETE CASCADE` 一起清掉；向量与落盘文件不归本层管，
    服务层必须显式清理 —— 外键清不掉 Chroma 里的向量，残留的片段会继续被检索命中。
    """
    session.delete(row)
    session.flush()


# -----------------------------------------------------------------------------
# 文档
# -----------------------------------------------------------------------------
def create_document(
    session: Session,
    *,
    kb_id: int,
    user_id: int,
    filename: str,
    ext: str,
    size_bytes: int,
) -> KnowledgeDocument:
    """建一条文档记录，初始状态 `pending`（等后台线程来推）。

    `user_id` 是**冗余属主**（`kb_id` 已经能导出来）：越权判断要走最短的查询路径，
    不为拿它去 JOIN 一次 `knowledge_bases`（见 `sql/07_knowledge_base.sql` 文件头）。
    """
    row = KnowledgeDocument(
        kb_id=int(kb_id),
        user_id=int(user_id),
        filename=filename,
        ext=ext,
        size_bytes=int(size_bytes),
        status="pending",
    )
    session.add(row)
    session.flush()
    return row


def get_document(
    session: Session, doc_id: int, *, user_id: int | None = None
) -> KnowledgeDocument | None:
    """按 id 取文档；传 `user_id` 时同时校验归属（不属于则返回 `None`）。"""
    row = session.get(KnowledgeDocument, int(doc_id))
    if row is None:
        return None
    if user_id is not None and int(row.user_id) != int(user_id):
        return None
    return row


def list_documents(session: Session, *, kb_id: int) -> list[KnowledgeDocument]:
    """某库的全部文档，**按上传先后**（id 升序）。

    不用 `created_at`：同一批上传的几份文档时间戳可能完全相同，
    而解析进度页希望顺序稳定（否则每次轮询列表都在跳）。
    """
    return list(
        session.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.kb_id == int(kb_id))
            .order_by(KnowledgeDocument.id.asc())
        ).all()
    )


def document_paths(session: Session, *, kb_id: int) -> list[tuple[int, str]]:
    """某库全部文档的 `(id, ext)` —— 删库时据此把落盘文件也清掉。

    只取两列：删库那一刻不需要文件名与状态，把整行拉回来只是徒增内存。
    """
    return [
        (int(doc_id), str(ext))
        for doc_id, ext in session.execute(
            select(KnowledgeDocument.id, KnowledgeDocument.ext).where(
                KnowledgeDocument.kb_id == int(kb_id)
            )
        ).all()
    ]


def count_documents(session: Session, *, kb_id: int) -> int:
    """某库的文档总数（含解析中与失败的）。"""
    return int(
        session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.kb_id == int(kb_id))
        )
        or 0
    )


def count_documents_by_status(session: Session, *, kb_id: int) -> dict[str, int]:
    """按状态计数，**四个键恒在**（不存在的补 0）。

    补 0 是有意的：调用方（界面上的状态分布）想做 `by_status["failed"]`
    这种直读，缺键会让它拿到 `KeyError` 而不是一个「0 份」的事实。
    """
    rows = session.execute(
        select(KnowledgeDocument.status, func.count())
        .where(KnowledgeDocument.kb_id == int(kb_id))
        .group_by(KnowledgeDocument.status)
    ).all()
    counts = {status: 0 for status in DOC_STATUSES}
    for status, amount in rows:
        counts[str(status)] = int(amount)
    return counts


def count_ready_documents(session: Session, *, kb_id: int) -> int:
    """**已就绪**的文档数。

    它是「这个库能不能检索出东西」的唯一前置判据：非 `ready` 的文档一条向量都没有，
    所以「库里有文档」与「库里有可检索的内容」是两件事（spec 要求系统能区分
    「库是空的」与「检索没命中」）。
    """
    return int(
        session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(
                KnowledgeDocument.kb_id == int(kb_id),
                KnowledgeDocument.status == "ready",
            )
        )
        or 0
    )


# -----------------------------------------------------------------------------
# 状态迁移（解析线程与接口层都走这三个函数，没有第四种写法）
# -----------------------------------------------------------------------------
def mark_parsing(session: Session, row: KnowledgeDocument) -> None:
    """置为「解析中」，并**清掉上一次的失败痕迹**。

    为什么必须清：重试一份之前失败的文档时，界面会在「正在解析」的旁边
    继续显示上一次的错误原因 —— 用户看到的是自相矛盾的两句话。
    """
    row.status = "parsing"
    row.error_code = ""
    row.error_message = ""
    row.parsed_at = None
    session.flush()


def mark_ready(
    session: Session, row: KnowledgeDocument, *, chunk_count: int, page_count: int = 0
) -> None:
    """置为「已就绪」，记录片段数与页数。"""
    row.status = "ready"
    row.chunk_count = max(0, int(chunk_count))
    row.page_count = max(0, int(page_count))
    row.error_code = ""
    row.error_message = ""
    row.parsed_at = utcnow()
    session.flush()


def mark_failed(session: Session, row: KnowledgeDocument, *, code: str, message: str) -> None:
    """置为「解析失败」，记下可诊断的原因。

    ⚠️ **`chunk_count` 归零**：重新解析一份曾经成功过的文档、这次失败时，
    残留的上一次片段数会让界面显示「已切分 12 个片段 · 解析失败」——
    既自相矛盾，又会让用户以为资料还能用。

    `page_count` **不动**：PDF 的页数是文件本身的事实，与解析成不成功无关
    （扫描件 PDF 能数出 20 页）。把它清零等于抹掉一条真实信息。

    `code` 给排查聚合用、`message` 给用户看（spec 要求两者分开存放）——
    所以调用方必须保证 `message` 是一句可展示的话，不是堆栈或上游报文。
    """
    row.status = "failed"
    row.chunk_count = 0
    row.error_code = (code or "")[:32]
    row.error_message = (message or "")[:255]
    row.parsed_at = utcnow()
    session.flush()


def delete_document(session: Session, row: KnowledgeDocument) -> None:
    """删文档（**只删数据库行**，向量与文件由服务层清）。"""
    session.delete(row)
    session.flush()
