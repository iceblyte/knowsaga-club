"""挑战与结算（方案 §6.3）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/attempts` | **服务端权威结算** |
| POST | `/attempts/{attempt_id}/retry` | 重做同一卷轴 → 返回题库快照 |

两个端点都要求登录，且卷轴 / 挑战记录必须属于当前用户，
否则一律按「资源不存在或无权访问」（4005）处理 —— 与「真的不存在」同形。
"""

from __future__ import annotations

from fastapi import APIRouter, Path

from app.api.deps import CurrentUser, DbSession
from app.core.response import ok
from app.models.attempt import AttemptSubmitRequest
from app.services import attempt_service

router = APIRouter(tags=["attempts"])


@router.post("/attempts", summary="提交本局作答并结算")
def submit_attempt(
    payload: AttemptSubmitRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """服务端权威结算。

    入参是**逐题选择**而不是分数：服务端用题目快照重新判定，
    所以档案里的经验、等级、正确率都不可能是客户端编出来的。

    `client_token` 是幂等键：网络重试复用同一个值只会得到同一份结果，
    不会产生第二条挑战记录。
    """
    result = attempt_service.submit_attempt(session, user, payload)
    return ok(result.model_dump(mode="json"))


@router.post("/attempts/{attempt_id}/retry", summary="重做同一卷轴")
def retry_attempt(
    user: CurrentUser,
    session: DbSession,
    attempt_id: str = Path(description="挑战记录 id（数字字符串）"),
) -> dict:
    """取回这一局所用卷轴的题库快照。

    返回的形状与出题链的 `Quiz` 完全一致，前端拿到就能直接开局 ——
    重做与首次挑战走的是同一条交卷路径。
    """
    result = attempt_service.retry_attempt(session, user, _as_id(attempt_id))
    return ok(result)


def _as_id(raw: str) -> int:
    """路径参数转 id。

    非法形状返回 4000（参数不对）而不是 4005：前者是调用方写错了 URL，
    后者是「这条记录不是你的」。两者都不该泄漏信息，但提示语不同。
    """
    from app.core.exceptions import invalid_param

    value = (raw or "").strip()
    if not (value.isascii() and value.isdigit()):
        raise invalid_param("挑战记录 id 必须是十进制字符串")
    return int(value)
