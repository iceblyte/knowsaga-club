"""业务错误码与统一异常。

错误码口径见 docs/MVP开发计划.md §7.6：

| 码   | 含义                     |
|------|--------------------------|
| 0    | 成功                     |
| 4000 | 参数校验失败             |
| 4001 | 输入内容不合规           |
| 4004 | 任务不存在或已过期       |
| 4090 | 任务不可取消（已结束）   |
| 5000 | 服务内部错误             |
| 5001 | AI 生成失败（已重试仍失败）|
| 5030 | AI 服务超时              |
| 5031 | 上游配额或限流           |
"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码。0 为成功，其余按 HTTP 语义分组。"""

    OK = 0

    # 4xxx 客户端错误
    INVALID_PARAM = 4000
    INVALID_INPUT = 4001
    TASK_NOT_FOUND = 4004
    TASK_NOT_CANCELLABLE = 4090

    # 5xxx 服务端错误
    INTERNAL_ERROR = 5000
    AI_GENERATION_FAILED = 5001
    AI_TIMEOUT = 5030
    AI_QUOTA_EXCEEDED = 5031


# 错误码 -> 默认中文提示（前端可直接展示）
DEFAULT_MESSAGES: dict[int, str] = {
    ErrorCode.OK: "ok",
    ErrorCode.INVALID_PARAM: "请求参数有误",
    ErrorCode.INVALID_INPUT: "输入内容不合规",
    ErrorCode.TASK_NOT_FOUND: "任务不存在或已过期",
    ErrorCode.TASK_NOT_CANCELLABLE: "任务已结束，无法取消",
    ErrorCode.INTERNAL_ERROR: "服务开小差了，请稍后重试",
    ErrorCode.AI_GENERATION_FAILED: "出题失败，请重试",
    ErrorCode.AI_TIMEOUT: "出题超时，请重试",
    ErrorCode.AI_QUOTA_EXCEEDED: "服务繁忙，请稍后重试",
}

# 错误码 -> HTTP 状态码
HTTP_STATUS: dict[int, int] = {
    ErrorCode.OK: 200,
    ErrorCode.INVALID_PARAM: 400,
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.TASK_NOT_CANCELLABLE: 409,
    ErrorCode.INTERNAL_ERROR: 500,
    # 502：上游（AI 服务）异常
    ErrorCode.AI_GENERATION_FAILED: 502,
    ErrorCode.AI_TIMEOUT: 504,
    ErrorCode.AI_QUOTA_EXCEEDED: 503,
}


class AppError(Exception):
    """业务异常。由全局异常处理器转换为统一响应体。

    Args:
        code: `ErrorCode` 成员或原始 int。
        message: 覆盖默认提示；不传则用 `DEFAULT_MESSAGES`。
        detail: 仅写日志用，**不会返回给前端**（避免泄露上游报文）。
    """

    def __init__(
        self,
        code: ErrorCode | int,
        message: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.code = int(code)
        self.message = message or DEFAULT_MESSAGES.get(self.code, "未知错误")
        self.detail = detail
        super().__init__(f"[{self.code}] {self.message}")

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)


# ---------- 常用异常的语义化构造 ----------

def invalid_input(message: str | None = None, detail: str | None = None) -> AppError:
    return AppError(ErrorCode.INVALID_INPUT, message, detail)


def invalid_param(message: str | None = None, detail: str | None = None) -> AppError:
    return AppError(ErrorCode.INVALID_PARAM, message, detail)


def task_not_found(task_id: str = "") -> AppError:
    return AppError(ErrorCode.TASK_NOT_FOUND, detail=f"task_id={task_id}")


def task_not_cancellable(task_id: str = "") -> AppError:
    return AppError(ErrorCode.TASK_NOT_CANCELLABLE, detail=f"task_id={task_id}")


def ai_generation_failed(detail: str | None = None) -> AppError:
    return AppError(ErrorCode.AI_GENERATION_FAILED, detail=detail)


def ai_timeout(detail: str | None = None) -> AppError:
    return AppError(ErrorCode.AI_TIMEOUT, detail=detail)
