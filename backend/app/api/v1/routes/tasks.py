"""任务轮询与取消。

quiz 与 report 共用这一组端点：`task_type` 字段区分类型，`quiz` / `report`
两个数据字段里永远只有一个是非空的。共用而不是各写一套，是因为前端的轮询逻辑
（间隔、超时、取消按钮、失败重试）对两种任务完全一致，分成两套只会重复三遍。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.response import ok
from app.services import quiz_service, task_service

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}", summary="轮询任务状态")
def get_task(task_id: str) -> dict:
    """返回任务的完整状态（形状固定的 10 个字段，见 `task_service.to_payload`）。

    任务不存在或已过期时抛 `AppError(4004)`，由全局异常处理器转成 404。
    """
    record = quiz_service.get_task_for_polling(task_id)
    return ok(task_service.to_payload(record))


@router.post("/tasks/{task_id}/cancel", summary="取消任务")
def cancel_task(task_id: str) -> dict:
    """取消任务。

    任务已结束（成功 / 失败 / 已取消）时抛 `AppError(4090)` —— 重复点击取消
    不该静默成功，否则前端会以为「取消生效了」，而实际上出题可能已经完成。
    """
    record = task_service.cancel_task(task_id)
    return ok({"status": record.status})
