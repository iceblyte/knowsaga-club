"""任务表：进程内内存存储 + TTL。

## 为什么不是数据库

已确认的决策：**MVP 不做后端持久化**。任务是纯粹的过程状态 ——
用户在「副本召唤中」等 10 秒，拿到题库之后任务就没用了。
把它写进数据库只会带来「谁来清理」「怎么处理并发写」这些与产品无关的问题。

## 这里最容易被忽略的两件事

**1. TTL 用 `time.monotonic` 而不是 `time.time`。**
墙上时钟会因为 NTP 校时或用户手动改时间而跳变，跳变会让任务要么提前过期、
要么永不过期。单调时钟只保证「一直往前走」，正是 TTL 需要的语义。

**2. 过期是「惰性 + 主动」两条路一起走。**
读的时候顺手判过期（惰性），保证任何时刻读到的都不是过期数据；
再提供一个 `cleanup_expired()` 让调用方（或未来的定时任务）主动回收，
否则没人访问过的过期任务会一直占着内存。

## 并发

出题跑在后台线程里，而读接口跑在请求线程里，两边同时操作同一份字典。
所有读写都在一把 `RLock` 内完成；返回给调用方的始终是**副本**，
避免调用方拿到引用后又去改它，绕过这里的状态机。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.exceptions import task_not_cancellable, task_not_found
from app.models.quiz import Quiz

TaskType = Literal["quiz", "report"]
TaskStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
StepStatus = Literal["pending", "running", "done", "failed"]

#: 终态：进入之后状态不再变化，任务也不可再取消
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})

#: 可替换的时钟（单调递增）。测试用它把「600 秒后过期」压缩到零耗时。
_clock: Callable[[], float] = time.monotonic


class TaskStep(BaseModel):
    """进度条上的一步。文案由后端给，前端直接渲染（§7.3）。"""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(description="步骤标识，如 retrieve / generate / validate")
    name: str = Field(description="展示名，如「理解你的输入」")
    status: StepStatus = Field(default="pending", description="步骤状态")
    detail: str = Field(default="", description="详情文案，如「正在生成第 4 / 5 题」")


class TaskError(BaseModel):
    """任务失败原因。`code` 复用 `ErrorCode`，前端据此决定重试还是提示配置问题。"""

    model_config = ConfigDict(extra="ignore")

    code: int = Field(description="业务错误码")
    message: str = Field(description="可直接展示的中文提示")


class TaskRecord(BaseModel):
    """一条任务记录。序列化后即为 §7.3 的轮询响应体。"""

    model_config = ConfigDict(extra="ignore")

    task_id: str
    task_type: TaskType
    status: TaskStatus = "pending"
    progress: int = Field(default=0, description="0–100")
    steps: list[TaskStep] = Field(default_factory=list)
    quiz: Quiz | None = Field(default=None, description="quiz 任务成功后填充")
    report: dict | None = Field(default=None, description="report 任务成功后填充（Phase 3）")
    error: TaskError | None = Field(default=None, description="失败时填充")
    created_at: float = Field(default=0.0, description="创建时刻（单调时钟）")
    updated_at: float = Field(default=0.0, description="最后更新时刻（单调时钟）")

    # 到期时刻。**不对外返回**：客户端不需要知道，公开它只会让前端开始算倒计时，
    # 而正确的做法是后端直接告诉它「任务不存在或已过期」（4004）。
    expires_at: float = Field(default=0.0, exclude=True)


def is_finished(status: str) -> bool:
    """任务是否已进入终态。"""
    return status in TERMINAL_STATUSES


# -----------------------------------------------------------------------------
# 进程内存储
# -----------------------------------------------------------------------------
# 声明在 TaskRecord 之后：`dict[str, TaskRecord]` 在模块加载时就要能解析出类型。
_lock = threading.RLock()
_tasks: dict[str, TaskRecord] = {}


# -----------------------------------------------------------------------------
# 内部工具
# -----------------------------------------------------------------------------
def _ttl_seconds() -> float:
    """每次都从配置现取 —— 测试与运行期改配置都能立刻生效。"""
    return float(get_settings().quiz_task_ttl_seconds)


def _clamp_progress(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


def _purge_locked(task_id: str) -> None:
    """在锁内判过期并清除。"""
    record = _tasks.get(task_id)
    if record is not None and _clock() >= record.expires_at > 0:
        _tasks.pop(task_id, None)


# -----------------------------------------------------------------------------
# 创建 / 读取
# -----------------------------------------------------------------------------
def create_task(task_type: TaskType, *, steps: list[TaskStep] | None = None) -> TaskRecord:
    """新建一条 `pending` 任务。"""
    from app.utils.id_generator import new_task_id

    now = _clock()
    record = TaskRecord(
        task_id=new_task_id(),
        task_type=task_type,
        status="pending",
        progress=0,
        steps=list(steps or []),
        created_at=now,
        updated_at=now,
        expires_at=now + _ttl_seconds(),
    )
    with _lock:
        _tasks[record.task_id] = record
    return record.model_copy(deep=True)


def get_task_or_none(task_id: str) -> TaskRecord | None:
    """按 ID 取任务；不存在或已过期返回 `None`。"""
    with _lock:
        _purge_locked(task_id)
        record = _tasks.get(task_id)
        return record.model_copy(deep=True) if record is not None else None


def get_task(task_id: str) -> TaskRecord:
    """按 ID 取任务；不存在或已过期抛 `AppError(4004)`。"""
    record = get_task_or_none(task_id)
    if record is None:
        raise task_not_found(task_id)
    return record


# -----------------------------------------------------------------------------
# 更新
# -----------------------------------------------------------------------------
def update_task(task_id: str, **changes: object) -> TaskRecord:
    """就地更新若干字段。

    Raises:
        AppError: 4004 任务不存在或已过期。
        TypeError: 传入了 `TaskRecord` 上不存在的字段。这是刻意的 ——
            拼错字段名的静默失败会让进度条永远停在原地，很难查。
    """
    unknown = set(changes) - set(TaskRecord.model_fields)
    if unknown:
        raise TypeError(f"TaskRecord 没有这些字段：{sorted(unknown)}")

    with _lock:
        _purge_locked(task_id)
        record = _tasks.get(task_id)
        if record is None:
            raise task_not_found(task_id)

        payload: dict[str, object] = dict(changes)
        if "progress" in payload:
            payload["progress"] = _clamp_progress(payload["progress"])
        # 补上的字段同样要过一遍校验，避免把非法字符串写进 Literal 字段
        payload["updated_at"] = _clock()

        updated = TaskRecord.model_validate({**record.model_dump(), **payload})
        updated.expires_at = record.expires_at  # model_dump 不含它，需手动带回
        _tasks[task_id] = updated
        return updated.model_copy(deep=True)


def cancel_task(task_id: str) -> TaskRecord:
    """取消任务。

    Raises:
        AppError: 4004 任务不存在；4090 任务已结束（含已取消）。
    """
    with _lock:
        _purge_locked(task_id)
        record = _tasks.get(task_id)
        if record is None:
            raise task_not_found(task_id)
        if is_finished(record.status):
            raise task_not_cancellable(task_id)

    return update_task(task_id, status="cancelled")


# -----------------------------------------------------------------------------
# 生命周期
# -----------------------------------------------------------------------------
def cleanup_expired() -> int:
    """清掉所有过期任务，返回清除数量。"""
    now = _clock()
    with _lock:
        stale = [tid for tid, rec in _tasks.items() if rec.expires_at > 0 and now >= rec.expires_at]
        for task_id in stale:
            _tasks.pop(task_id, None)
    return len(stale)


def reset_store() -> None:
    """清空任务表（测试用）。"""
    with _lock:
        _tasks.clear()


def to_payload(record: TaskRecord) -> dict:
    """序列化成轮询端点返回的 `data` 结构。

    形状是**固定 10 个键**，不随任务类型变化 —— 前端只写一套解析逻辑。
    没有值的字段一律给 `null`，而不是省略键：省略会让前端到处写 `?.`，
    而这类防御代码一旦漏掉一处就是线上白屏。
    """
    return record.model_dump(mode="json")
