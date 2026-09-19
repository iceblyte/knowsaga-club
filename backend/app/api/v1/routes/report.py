"""冒险日志（复盘报告）接口。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/report/generate` | 校验归属 + 入队，立刻返回 `task_id` |

生成结果**不在这里返回**：它通过 `GET /tasks/{task_id}` 轮询（`data.report`），
与出题链共用同一套轮询端点。这样前端只需要写一次轮询逻辑，
而「报告还在写」和「题目还在出」在界面上是同一件事。

## 为什么收 `attempt_id` 而不是收作答内容

见 `models/report.py` 的 `ReportGenerateRequest` 说明：Phase B 之后服务端已经
持有权威作答（`attempts` + `answers`），再让客户端回传一份就等于把权威性让回去。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.response import ok
from app.models.report import ReportGenerateRequest
from app.services import report_service

router = APIRouter(tags=["report"])


@router.post("/report/generate", summary="创建报告生成任务")
def create_report_task(
    payload: ReportGenerateRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """校验这次挑战属于当前用户，然后创建异步报告任务。

    已有可用报告且 `force=false` 时，任务会**直接以成功状态**返回，不排模型队列 ——
    所以用户重复点「看报告」既不会多花一次模型调用，也不会重写库里的报告。

    Raises:
        AppError(4000) —— `attempt_id` 形状非法（不是数据库 id 的十进制字符串）。
        AppError(4005) —— 挑战记录不存在或不属于当前用户（两者同形）。
    """
    result = report_service.submit_report_request(session, user, payload)
    return ok(result.model_dump(mode="json"))
