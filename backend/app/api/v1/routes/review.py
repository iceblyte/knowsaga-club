"""复习关卡（旧识重温）的路由。

只有一个端点：用到期错题组一局。返回的是**普通题库契约** `Quiz`，
所以前端可以把它直接喂给既有的「确认 → 答题 → 交卷」链路 ——
复习不需要第二条交卷路径，这是刻意的：两条路径迟早会有一套评分口径漂移。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.response import ok
from app.services import review_service

router = APIRouter(prefix="/review", tags=["review"])


@router.post("/start")
def start_review(user: CurrentUser, session: DbSession) -> dict:
    """用到期错题组一局复习关卡。

    无入参：**取哪些题是服务端的事实**（谁到期了），不由客户端挑。
    让客户端传题号的话，用户就能反复只练最擅长的那一道。

    Raises:
        AppError: 4005 —— 没有到期的错题。
    """
    payload = review_service.start_review(session, user)
    return ok(payload.model_dump(mode="json"))
