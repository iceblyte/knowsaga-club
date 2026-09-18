"""任务表测试（对应 docs/MVP开发计划.md §10 的 `test_task_service.py`）。

覆盖：创建 / 查询 / 取消 / TTL 过期 / 重复取消 / 清理。

## 时钟为什么必须可注入

TTL 过期测试如果用 `time.sleep(601)` 去等，测试就跑不动了。所以 `task_service`
内部的时间来源是一个模块级可替换的 `_clock`，测试把它换成一个假时钟，
就能在零耗时下验证「过期」这条路径。这不是为测试而加的口子 ——
`cleanup_expired()` 在真实运行时也需要一个统一的「现在」，
否则一次清理里每个任务各自取一次时间，边界会上蹿下跳。
"""

from __future__ import annotations

import pytest

from app.core.exceptions import AppError, ErrorCode
from app.services import task_service as ts


@pytest.fixture(autouse=True)
def _clean_store():
    """每个用例独占一份空表，避免用例互相看到对方创建的任务。"""
    ts.reset_store()
    yield
    ts.reset_store()


# -----------------------------------------------------------------------------
# 创建与查询
# -----------------------------------------------------------------------------
def test_create_task_returns_pending_record() -> None:
    rec = ts.create_task("quiz", user_id=1)

    assert rec.task_type == "quiz"
    assert rec.status == "pending"
    assert rec.progress == 0
    assert rec.quiz is None
    assert rec.error is None


def test_task_id_has_prefix_and_is_unique() -> None:
    ids = {ts.create_task("quiz", user_id=1).task_id for _ in range(50)}

    assert len(ids) == 50, "任务 ID 必须唯一"
    for task_id in ids:
        assert task_id.startswith("task_"), f"ID 前缀应为 task_，实际 {task_id!r}"


def test_get_task_returns_same_record() -> None:
    created = ts.create_task("quiz", user_id=1)

    fetched = ts.get_task(created.task_id)

    assert fetched.task_id == created.task_id
    assert fetched.status == "pending"


def test_get_unknown_task_raises_4004() -> None:
    with pytest.raises(AppError) as exc:
        ts.get_task("task_does_not_exist")

    assert exc.value.code == ErrorCode.TASK_NOT_FOUND


def test_get_task_or_none_returns_none_for_unknown() -> None:
    assert ts.get_task_or_none("task_nope") is None


# -----------------------------------------------------------------------------
# 更新
# -----------------------------------------------------------------------------
def test_update_task_patches_fields() -> None:
    rec = ts.create_task("quiz", user_id=1)

    updated = ts.update_task(
        rec.task_id,
        status="running",
        progress=42,
        steps=[ts.TaskStep(key="generate", name="生成闯关题目", status="running", detail="3 / 5")],
    )

    assert updated.status == "running"
    assert updated.progress == 42
    assert updated.steps[0].detail == "3 / 5"
    # 更新是就地生效的：再查一次拿到的是同一份最新状态
    assert ts.get_task(rec.task_id).progress == 42


def test_update_unknown_task_raises_4004() -> None:
    with pytest.raises(AppError) as exc:
        ts.update_task("task_nope", progress=10)

    assert exc.value.code == ErrorCode.TASK_NOT_FOUND


def test_update_rejects_unknown_field() -> None:
    rec = ts.create_task("quiz", user_id=1)

    with pytest.raises(TypeError):
        ts.update_task(rec.task_id, not_a_field=1)  # type: ignore[call-arg]


# -----------------------------------------------------------------------------
# 取消
# -----------------------------------------------------------------------------
def test_cancel_pending_task() -> None:
    rec = ts.create_task("quiz", user_id=1)

    cancelled = ts.cancel_task(rec.task_id)

    assert cancelled.status == "cancelled"


def test_cancel_running_task() -> None:
    rec = ts.create_task("quiz", user_id=1)
    ts.update_task(rec.task_id, status="running", progress=30)

    assert ts.cancel_task(rec.task_id).status == "cancelled"


@pytest.mark.parametrize("final_status", ["succeeded", "failed", "cancelled"])
def test_cancel_ended_task_raises_4090(final_status: str) -> None:
    """已结束（含已取消）的任务再取消一律 4090 —— 保证重复点击不会静默成功。"""
    rec = ts.create_task("quiz", user_id=1)
    ts.update_task(rec.task_id, status=final_status)  # type: ignore[arg-type]

    with pytest.raises(AppError) as exc:
        ts.cancel_task(rec.task_id)

    assert exc.value.code == ErrorCode.TASK_NOT_CANCELLABLE


def test_cancel_unknown_task_raises_4004() -> None:
    with pytest.raises(AppError) as exc:
        ts.cancel_task("task_nope")

    assert exc.value.code == ErrorCode.TASK_NOT_FOUND


def test_cancelled_task_is_not_cancellable_twice() -> None:
    rec = ts.create_task("quiz", user_id=1)
    ts.cancel_task(rec.task_id)

    with pytest.raises(AppError) as exc:
        ts.cancel_task(rec.task_id)

    assert exc.value.code == ErrorCode.TASK_NOT_CANCELLABLE


# -----------------------------------------------------------------------------
# TTL
# -----------------------------------------------------------------------------
def test_task_expires_after_ttl(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    now = {"t": 1_000.0}
    monkeypatch.setattr(ts, "_clock", lambda: now["t"])

    rec = ts.create_task("quiz", user_id=1)
    assert ts.get_task(rec.task_id).task_id == rec.task_id

    # 越过 TTL 边界
    now["t"] += settings.quiz_task_ttl_seconds + 0.5

    with pytest.raises(AppError) as exc:
        ts.get_task(rec.task_id)
    assert exc.value.code == ErrorCode.TASK_NOT_FOUND


def test_task_alive_just_before_ttl(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    now = {"t": 1_000.0}
    monkeypatch.setattr(ts, "_clock", lambda: now["t"])

    rec = ts.create_task("quiz", user_id=1)
    now["t"] += settings.quiz_task_ttl_seconds - 0.5

    assert ts.get_task(rec.task_id).status == "pending"


def test_cleanup_expired_removes_only_stale_tasks(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    now = {"t": 1_000.0}
    monkeypatch.setattr(ts, "_clock", lambda: now["t"])

    stale = ts.create_task("quiz", user_id=1)
    now["t"] += settings.quiz_task_ttl_seconds + 1
    fresh = ts.create_task("quiz", user_id=1)

    removed = ts.cleanup_expired()

    assert removed == 1
    assert ts.get_task_or_none(stale.task_id) is None
    assert ts.get_task_or_none(fresh.task_id) is not None


def test_cleanup_expired_is_idempotent(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    now = {"t": 1_000.0}
    monkeypatch.setattr(ts, "_clock", lambda: now["t"])

    ts.create_task("quiz", user_id=1)
    now["t"] += settings.quiz_task_ttl_seconds + 1

    assert ts.cleanup_expired() == 1
    assert ts.cleanup_expired() == 0


def test_reset_store_clears_everything() -> None:
    rec = ts.create_task("quiz", user_id=1)

    ts.reset_store()

    assert ts.get_task_or_none(rec.task_id) is None


# -----------------------------------------------------------------------------
# steps / 进度
# -----------------------------------------------------------------------------
def test_task_step_default_detail_is_empty() -> None:
    step = ts.TaskStep(key="retrieve", name="理解你的输入", status="pending")

    assert step.detail == ""


def test_progress_is_clamped_to_0_100() -> None:
    rec = ts.create_task("quiz", user_id=1)

    assert ts.update_task(rec.task_id, progress=-5).progress == 0
    assert ts.update_task(rec.task_id, progress=140).progress == 100


def test_quiz_payload_is_kept_intact(sample_quiz_payload: dict) -> None:
    """`quiz` 字段保存的是已通过 Pydantic 校验的 Quiz，出口时内容原样返回。

    这里断言「相等」而不是「同一个对象」：任务表对外一律给副本，
    否则调用方拿到引用后随手改一下，就绕过了状态机。
    """
    from app.models.quiz import Quiz

    rec = ts.create_task("quiz", user_id=1)
    quiz = Quiz.model_validate(sample_quiz_payload)

    ts.update_task(rec.task_id, status="succeeded", progress=100, quiz=quiz)

    restored = ts.get_task(rec.task_id).quiz
    assert restored == quiz
    assert restored is not quiz, "出口必须是副本，不能把内部引用递出去"
