"""任务轮询与取消。

quiz 与 report 共用这一组端点：`task_type` 字段区分类型，`quiz` / `report`
两个数据字段里永远只有一个是非空的。共用而不是各写一套，是因为前端的轮询逻辑
（间隔、超时、取消按钮、失败重试）对两种任务完全一致，分成两套只会重复三遍。

## 归属校验：越权一律按「不存在」处理

两个端点都要求登录，并且校验**任务属于当前用户**。不是自己的任务返回 4004，
与「任务不存在或已过期」**完全同形** —— 这样业务码差异不会告诉攻击者
「这个 task_id 真实存在，只是不是你的」。

为什么不给越权单独用 4005：方案 §4.6 的错误码表把「任务」也列进了 4005，
但 §4.3 的鉴权矩阵明确写的是「任务归属当前用户，**否则按「不存在」处理**」。
两处冲突时采纳 §4.3，理由有三条：

1. 同一个端点对「你拿不到这个任务」这一件事返回两个不同的码，前端就得写两个
   分支去提示，而两条文案对用户是同一句话。
2. 4005 的默认提示是「内容不存在或已删除」，用在十几分钟就过期的任务上不合适；
   4004 的「任务不存在或已过期」才准确。
3. 4005 与 4004 的差异本身就是一次信息泄漏。任务 id 是随机串、任务本身还会过期，
   合并两者没有任何代价。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.response import ok
from app.services import quiz_service, task_service

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}", summary="轮询任务状态")
def get_task(task_id: str, user: CurrentUser) -> dict:
    """返回任务的完整状态（形状固定的 10 个字段，见 `task_service.to_payload`）。

    任务不存在、已过期、或不属于当前用户时抛 `AppError(4004)`，
    由全局异常处理器转成 404。
    """
    record = quiz_service.get_task_for_polling(task_id, user_id=int(user.id))
    return ok(task_service.to_payload(record))


@router.post("/tasks/{task_id}/cancel", summary="取消任务")
def cancel_task(task_id: str, user: CurrentUser) -> dict:
    """取消任务。

    任务已结束（成功 / 失败 / 已取消）时抛 `AppError(4090)` —— 重复点击取消
    不该静默成功，否则前端会以为「取消生效了」，而实际上出题可能已经完成。

    归属校验放在取消动作**之前**：否则一个越权的取消请求会真的把别人的任务停掉，
    而返回体却和「任务不存在」一样 —— 那就成了「悄悄地破坏了别人的数据」。
    """
    # 先做归属校验（不通过即 4004），再做状态机的取消
    quiz_service.get_task_for_polling(task_id, user_id=int(user.id))
    record = task_service.cancel_task(task_id)
    return ok({"status": record.status})
