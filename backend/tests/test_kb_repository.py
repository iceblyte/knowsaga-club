"""知识库数据层的取数与约束（`app/services/kb_repository.py`）。

## 这里锁什么、不锁什么

**锁**：归属过滤的形状（越权与不存在必须同形）、级联删除、状态字段的写入、
以及「同一用户下库名唯一」这条数据库约束。

**不锁**：业务判定（准入、状态机的合法迁移、向量与文件怎么办）—— 那些在
`test_kb_service.py` 里。分开的理由与 `quiz_repository` / `quiz_service` 的分层相同：
本层只回答「这些行怎么存怎么读」，混进业务判定之后，改一个文案就要在两处之间来回看。

## 事务由调用方拥有

本层**不 commit**（唯一的例外见 `get_or_create_default_base` 的嵌套事务）。
所以用例里能明确看到「哪一步落库了」—— 而 `service` 层的失败路径（比如解析失败）
正好依赖「先写进去再改状态」这件事能被控制。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.constants import KB_DEFAULT_NAME
from app.db.tables import KnowledgeBase, KnowledgeDocument
from app.services import kb_repository
from tests.helpers import make_user, user_id_of


@pytest.fixture
def user(db_session):  # noqa: ANN001, ANN201
    return make_user(db_session, openid="kb-user-1")


@pytest.fixture
def other_user(db_session):  # noqa: ANN001, ANN201
    return make_user(db_session, openid="kb-user-2", nickname="另一个人")


def _base(session, user, *, name: str = "机器学习资料", description: str = "课程讲义"):  # noqa: ANN001, ANN202
    row = kb_repository.create_base(session, user_id=user_id_of(user), name=name, description=description)
    session.commit()
    return row


# -----------------------------------------------------------------------------
# 1. 建库
# -----------------------------------------------------------------------------
def test_create_base_persists_fields(db_session, user) -> None:  # noqa: ANN001
    row = _base(db_session, user)

    assert int(row.id) > 0
    assert row.name == "机器学习资料"
    assert row.description == "课程讲义"
    assert int(row.user_id) == user_id_of(user)
    assert row.created_at is not None


def test_base_name_is_unique_per_user(db_session, user) -> None:  # noqa: ANN001
    """同名库在同一用户下会被数据库拒绝。

    为什么需要它：用户在列表里看到一个同名同描述的库时，**分不出该选哪个**。
    把这条钉在数据层，服务层才能放心地把 `IntegrityError` 翻译成一句可展示的提示。
    """
    _base(db_session, user)
    with pytest.raises(IntegrityError):
        kb_repository.create_base(db_session, user_id=user_id_of(user), name="机器学习资料")
    db_session.rollback()


def test_same_name_is_fine_across_users(db_session, user, other_user) -> None:  # noqa: ANN001
    """唯一键是 `(user_id, name)`，不是 `name` —— 否则先注册的人会占掉一个常用词。"""
    _base(db_session, user)
    row = _base(db_session, other_user)

    assert row.name == "机器学习资料"


# -----------------------------------------------------------------------------
# 2. 取库：归属过滤
# -----------------------------------------------------------------------------
def test_find_base_by_name_is_scoped_to_user(db_session, user, other_user) -> None:  # noqa: ANN001
    _base(db_session, other_user)

    assert kb_repository.find_base_by_name(db_session, user_id=user_id_of(user), name="机器学习资料") is None
    assert (
        kb_repository.find_base_by_name(db_session, user_id=user_id_of(other_user), name="机器学习资料")
        is not None
    )


def test_get_base_hides_other_users_row(db_session, user, other_user) -> None:  # noqa: ANN001
    """别人的库返回 `None` —— 与「这个 id 不存在」逐位同形。

    ⚠️ 这是 spec「越权访问与不存在必须返回同一个结果」在数据层的落点。
    若这里改成抛异常或返回另一类结果，接口层就再也不可能做到同形了。
    """
    mine = _base(db_session, user)
    theirs = _base(db_session, other_user)

    assert kb_repository.get_base(db_session, int(mine.id), user_id=user_id_of(user)) is not None
    assert kb_repository.get_base(db_session, int(theirs.id), user_id=user_id_of(user)) is None
    assert kb_repository.get_base(db_session, 999_999_999, user_id=user_id_of(user)) is None


def test_list_bases_returns_only_own_newest_first(db_session, user, other_user) -> None:  # noqa: ANN001
    _base(db_session, user, name="先建的")
    _base(db_session, user, name="后建的")
    _base(db_session, other_user, name="别人的")

    rows = kb_repository.list_bases(db_session, user_id=user_id_of(user))

    assert [row.name for row in rows] == ["后建的", "先建的"]


# -----------------------------------------------------------------------------
# 3. 默认库：find-or-create
# -----------------------------------------------------------------------------
def test_get_or_create_default_base_creates_then_reuses(db_session, user) -> None:  # noqa: ANN001
    """第一次建、之后复用**同一个**库。

    原型里「新建知识库」是独立一屏，本期不做，库名由上传流程的默认库承载。
    所以这条「不会越传越多」的性质是必需的：每次上传都新建一个，
    用户点三次上传就会看到三个「我的知识库」。
    """
    first = kb_repository.get_or_create_default_base(db_session, user_id=user_id_of(user))
    db_session.commit()
    second = kb_repository.get_or_create_default_base(db_session, user_id=user_id_of(user))

    assert first.name == KB_DEFAULT_NAME
    assert int(first.id) == int(second.id)


def test_default_base_survives_a_racing_insert(db_session, user, monkeypatch) -> None:  # noqa: ANN001
    """并发下另一次请求抢先建好时，应**取用那一行**而不是把 IntegrityError 抛给用户。

    造法：让 `find_base_by_name` 第一次返回 `None`，逼代码走到插入分支 ——
    而那一行其实已经存在（模拟「查完之后、插之前」的窗口）。
    """
    existing = _base(db_session, user, name=KB_DEFAULT_NAME)

    real_find = kb_repository.find_base_by_name
    calls = {"n": 0}

    def flaky(session, *, user_id, name):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # 第一次「没查到」
        return real_find(session, user_id=user_id, name=name)

    monkeypatch.setattr(kb_repository, "find_base_by_name", flaky)
    row = kb_repository.get_or_create_default_base(db_session, user_id=user_id_of(user))

    assert int(row.id) == int(existing.id)
    assert calls["n"] >= 2, "撞到唯一键之后必须重查一次，而不是直接失败"


# -----------------------------------------------------------------------------
# 4. 改名与删库
# -----------------------------------------------------------------------------
def test_update_base_touches_only_given_fields(db_session, user) -> None:  # noqa: ANN001
    row = _base(db_session, user)

    kb_repository.update_base(db_session, row, name="深度学习资料")
    db_session.commit()

    assert row.name == "深度学习资料"
    assert row.description == "课程讲义", "没传的字段不该被清掉"


def test_delete_base_cascades_its_documents(db_session, user) -> None:  # noqa: ANN001
    """删库必须连带文档。

    这条由 `fk_knowledge_documents_kb ... ON DELETE CASCADE` 保证 ——
    但它**只清数据库行**，向量与落盘文件由服务层显式清理（见 `kb_service`）。
    """
    base = _base(db_session, user)
    kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="a.md", ext="md", size_bytes=10
    )
    db_session.commit()

    kb_repository.delete_base(db_session, base)
    db_session.commit()

    assert db_session.query(KnowledgeDocument).filter_by(kb_id=int(base.id)).count() == 0


# -----------------------------------------------------------------------------
# 5. 文档
# -----------------------------------------------------------------------------
def test_create_document_starts_pending(db_session, user) -> None:  # noqa: ANN001
    base = _base(db_session, user)

    doc = kb_repository.create_document(
        db_session,
        kb_id=int(base.id),
        user_id=user_id_of(user),
        filename="讲义.pdf",
        ext="pdf",
        size_bytes=1234,
    )

    assert int(doc.id) > 0
    assert doc.status == "pending"
    assert doc.chunk_count == 0
    assert doc.page_count == 0
    assert doc.parsed_at is None
    assert doc.error_code == ""
    assert doc.error_message == ""


def test_get_document_hides_other_users_row(db_session, user, other_user) -> None:  # noqa: ANN001
    mine = _base(db_session, user)
    theirs = _base(db_session, other_user)
    doc = kb_repository.create_document(
        db_session, kb_id=int(theirs.id), user_id=user_id_of(other_user), filename="b.md", ext="md", size_bytes=1
    )
    db_session.commit()

    assert kb_repository.get_document(db_session, int(doc.id), user_id=user_id_of(user)) is None
    assert kb_repository.get_document(db_session, int(doc.id), user_id=user_id_of(other_user)) is not None
    assert kb_repository.get_document(db_session, 999_999_999, user_id=user_id_of(user)) is None


def test_list_documents_is_scoped_and_ordered(db_session, user) -> None:  # noqa: ANN001
    base = _base(db_session, user)
    other = _base(db_session, user, name="另一个库")
    for name in ("第一份.md", "第二份.md"):
        kb_repository.create_document(
            db_session, kb_id=int(base.id), user_id=user_id_of(user), filename=name, ext="md", size_bytes=1
        )
    kb_repository.create_document(
        db_session, kb_id=int(other.id), user_id=user_id_of(user), filename="别的库.md", ext="md", size_bytes=1
    )

    rows = kb_repository.list_documents(db_session, kb_id=int(base.id))

    assert [row.filename for row in rows] == ["第一份.md", "第二份.md"]


# -----------------------------------------------------------------------------
# 6. 计数
# -----------------------------------------------------------------------------
def test_counts_distinguish_statuses(db_session, user) -> None:  # noqa: ANN001
    """`ready` 之外的状态都要能被数出来 —— 「库是空的」与「检索没命中」要能区分。"""
    base = _base(db_session, user)
    ids = []
    for name in ("a.md", "b.md", "c.md", "d.md"):
        doc = kb_repository.create_document(
            db_session, kb_id=int(base.id), user_id=user_id_of(user), filename=name, ext="md", size_bytes=1
        )
        ids.append(int(doc.id))
    kb_repository.mark_ready(db_session, kb_repository.get_document(db_session, ids[0]), chunk_count=3, page_count=0)
    kb_repository.mark_parsing(db_session, kb_repository.get_document(db_session, ids[1]))
    kb_repository.mark_failed(db_session, kb_repository.get_document(db_session, ids[2]), code="x", message="坏了")
    db_session.commit()

    assert kb_repository.count_documents(db_session, kb_id=int(base.id)) == 4
    assert kb_repository.count_ready_documents(db_session, kb_id=int(base.id)) == 1
    by_status = kb_repository.count_documents_by_status(db_session, kb_id=int(base.id))
    assert by_status == {"ready": 1, "parsing": 1, "failed": 1, "pending": 1}


# -----------------------------------------------------------------------------
# 7. 解析状态字段
# -----------------------------------------------------------------------------
def test_mark_ready_records_chunks_pages_and_time(db_session, user) -> None:  # noqa: ANN001
    base = _base(db_session, user)
    doc = kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="a.pdf", ext="pdf", size_bytes=1
    )

    kb_repository.mark_ready(db_session, doc, chunk_count=7, page_count=3)
    db_session.commit()

    assert doc.status == "ready"
    assert doc.chunk_count == 7
    assert doc.page_count == 3
    assert doc.parsed_at is not None


def test_mark_failed_clears_chunk_count(db_session, user) -> None:  # noqa: ANN001
    """失败时必须把 `chunk_count` 归零。

    重新解析一份**曾经成功过**的文档、这次失败了：残留的上一次片段数会让界面
    显示「已切分 12 个片段 · 解析失败」—— 自相矛盾，而且用户会以为资料还能用。
    """
    base = _base(db_session, user)
    doc = kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="a.pdf", ext="pdf", size_bytes=1
    )
    kb_repository.mark_ready(db_session, doc, chunk_count=12, page_count=3)

    kb_repository.mark_failed(db_session, doc, code="parse_failed", message="这份文件没能解析成功")
    db_session.commit()

    assert doc.status == "failed"
    assert doc.chunk_count == 0
    assert doc.error_code == "parse_failed"
    assert doc.error_message == "这份文件没能解析成功"
    assert doc.parsed_at is not None


def test_mark_parsing_clears_previous_failure(db_session, user) -> None:  # noqa: ANN001
    """重试时先把上一次的失败原因清掉，否则界面会一边转圈一边显示旧错误。"""
    base = _base(db_session, user)
    doc = kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="a.pdf", ext="pdf", size_bytes=1
    )
    kb_repository.mark_failed(db_session, doc, code="parse_failed", message="上次的原因")

    kb_repository.mark_parsing(db_session, doc)
    db_session.commit()

    assert doc.status == "parsing"
    assert doc.error_code == ""
    assert doc.error_message == ""
    assert doc.parsed_at is None


# -----------------------------------------------------------------------------
# 8. 删文档
# -----------------------------------------------------------------------------
def test_delete_document_removes_only_it(db_session, user) -> None:  # noqa: ANN001
    base = _base(db_session, user)
    keep = kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="留.md", ext="md", size_bytes=1
    )
    drop = kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="删.md", ext="md", size_bytes=1
    )
    db_session.commit()

    kb_repository.delete_document(db_session, drop)
    db_session.commit()

    remaining = db_session.query(KnowledgeDocument).filter_by(kb_id=int(base.id)).all()
    assert [row.filename for row in remaining] == ["留.md"]
    assert int(keep.id) > 0


def test_document_paths_lists_id_and_ext(db_session, user) -> None:  # noqa: ANN001
    """删库时要按 id + 扩展名把落盘文件也清掉，所以这里必须能一次取到这两样。"""
    base = _base(db_session, user)
    kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="a.pdf", ext="pdf", size_bytes=1
    )
    kb_repository.create_document(
        db_session, kb_id=int(base.id), user_id=user_id_of(user), filename="b.md", ext="md", size_bytes=1
    )
    db_session.commit()

    paths = kb_repository.document_paths(db_session, kb_id=int(base.id))

    assert [ext for _, ext in paths] == ["pdf", "md"]
    assert len({doc_id for doc_id, _ in paths}) == 2


def test_base_entity_is_knowledge_base(db_session, user) -> None:  # noqa: ANN001
    """防止有人把 `KnowledgeBase` 误换成别的映射（改表时最容易犯的错）。"""
    assert isinstance(_base(db_session, user), KnowledgeBase)
