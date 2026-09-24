"""业务错误码与统一异常。

错误码口径见 docs/MVP开发计划.md §7.6 与 docs/用户系统方案设计文档.md §4.6：

| 码   | 含义                     |
|------|--------------------------|
| 0    | 成功                     |
| 4000 | 参数校验失败             |
| 4001 | 输入内容不合规           |
| 4002 | 上传文件不合规           |
| 4004 | 任务不存在或已过期       |
| 4005 | 资源不存在或无权访问     |
| 4010 | 未登录或登录态无效       |
| 4011 | 微信登录凭证无效         |
| 4030 | 账号被限制登录           |
| 4090 | 任务不可取消（已结束）   |
| 4290 | 请求过于频繁             |
| 5000 | 服务内部错误             |
| 5001 | AI 生成失败（已重试仍失败）|
| 5030 | AI 服务超时              |
| 5031 | 上游配额或限流           |
| 5032 | 微信接口调用异常         |
"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码。0 为成功，其余按 HTTP 语义分组。"""

    OK = 0

    # 4xxx 客户端错误
    INVALID_PARAM = 4000
    INVALID_INPUT = 4001
    UPLOAD_INVALID = 4002
    TASK_NOT_FOUND = 4004
    #: 「资源不存在或无权访问」。越权与不存在**故意返回同一个码**：
    #: 若为越权单独设码，攻击者就能靠错误码差异探测「这条数据是否存在」。
    RESOURCE_NOT_FOUND = 4005
    TASK_NOT_CANCELLABLE = 4090

    # 身份与权限（HTTP 状态码见 HTTP_STATUS）
    UNAUTHORIZED = 4010
    WECHAT_CODE_INVALID = 4011
    ACCOUNT_BLOCKED = 4030
    RATE_LIMITED = 4290

    # 5xxx 服务端错误
    INTERNAL_ERROR = 5000
    AI_GENERATION_FAILED = 5001
    AI_TIMEOUT = 5030
    AI_QUOTA_EXCEEDED = 5031
    WECHAT_UPSTREAM_ERROR = 5032


# 错误码 -> 默认中文提示（前端可直接展示）
#
# 注意：4010 / 4011 / 4030 的文案是**给用户看的**，所以只说「该怎么做」，
# 不出现任何内部机制说明（沿用既有红线，见用户系统需求分析文档 §6.1 NFR-S8）。
DEFAULT_MESSAGES: dict[int, str] = {
    ErrorCode.OK: "ok",
    ErrorCode.INVALID_PARAM: "请求参数有误",
    ErrorCode.INVALID_INPUT: "输入内容不合规",
    ErrorCode.UPLOAD_INVALID: "头像不合规，请换一张图片",
    ErrorCode.TASK_NOT_FOUND: "任务不存在或已过期",
    ErrorCode.RESOURCE_NOT_FOUND: "内容不存在或已删除",
    ErrorCode.TASK_NOT_CANCELLABLE: "任务已结束，无法取消",
    ErrorCode.UNAUTHORIZED: "登录状态已过期，请重新进入小程序",
    ErrorCode.WECHAT_CODE_INVALID: "登录凭证已失效，请重新进入小程序",
    ErrorCode.ACCOUNT_BLOCKED: "该账号暂时无法登录",
    ErrorCode.RATE_LIMITED: "操作有点频繁，请稍后再试",
    ErrorCode.INTERNAL_ERROR: "服务开小差了，请稍后重试",
    ErrorCode.AI_GENERATION_FAILED: "出题失败，请重试",
    ErrorCode.AI_TIMEOUT: "出题超时，请重试",
    ErrorCode.AI_QUOTA_EXCEEDED: "服务繁忙，请稍后重试",
    ErrorCode.WECHAT_UPSTREAM_ERROR: "服务开小差了，请稍后重试",
}

# 错误码 -> HTTP 状态码
#
# 为什么 HTTP 状态码也必须对：前端的登录态拦截器与网关都按状态码判断，
# 只给业务码会让「401 触发静默重建」这条链路失效。
HTTP_STATUS: dict[int, int] = {
    ErrorCode.OK: 200,
    ErrorCode.INVALID_PARAM: 400,
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.UPLOAD_INVALID: 400,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.TASK_NOT_CANCELLABLE: 409,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.WECHAT_CODE_INVALID: 401,
    ErrorCode.ACCOUNT_BLOCKED: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    # 502：上游（AI 服务）异常
    ErrorCode.AI_GENERATION_FAILED: 502,
    ErrorCode.AI_TIMEOUT: 504,
    ErrorCode.AI_QUOTA_EXCEEDED: 503,
    ErrorCode.WECHAT_UPSTREAM_ERROR: 502,
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


# ---------- 用户系统新增 ----------

def unauthorized(detail: str | None = None) -> AppError:
    """登录态缺失/格式错/签名错/过期/版本号不匹配 —— 全部归到这一个码。"""
    return AppError(ErrorCode.UNAUTHORIZED, detail=detail)


def wechat_code_invalid(detail: str | None = None) -> AppError:
    """微信登录凭证无效或已被使用（上游 40029）。"""
    return AppError(ErrorCode.WECHAT_CODE_INVALID, detail=detail)


def account_blocked(detail: str | None = None) -> AppError:
    """账号被限制登录（上游 40226）。"""
    return AppError(ErrorCode.ACCOUNT_BLOCKED, detail=detail)


def wechat_upstream_error(detail: str | None = None) -> AppError:
    """微信接口系统繁忙或网络异常（上游 -1 或网络失败）。"""
    return AppError(ErrorCode.WECHAT_UPSTREAM_ERROR, detail=detail)


def rate_limited(detail: str | None = None) -> AppError:
    return AppError(ErrorCode.RATE_LIMITED, detail=detail)


def upload_invalid(message: str | None = None, detail: str | None = None) -> AppError:
    """上传文件不合规（4002）。

    ⚠️ **这个码是多个上传场景共用的，所以文案必须由调用方给。**
    不传时用的是 `DEFAULT_MESSAGES` 里那条**给头像写的**文案
    （「头像不合规，请换一张图片」），文档上传场景沿用它会得到一句文不对题的话。
    知识库那边踩过一次：传了字符串但走的是 `detail` 参数，
    于是文案落进了「只写日志」的槽位，用户看到的是头像那句。

    Args:
        message: 给用户看的那句话。**不传就用头像场景的默认文案。**
        detail: 仅写日志用，不会返回给前端。

    另注：`4002` 的语义是「上传文件不合规」，**不是**「内容不合规」——
    后者是 `4001`。文档格式 / 体积不合规属于前者，所以不新增错误码（design D9）。
    """
    return AppError(ErrorCode.UPLOAD_INVALID, message, detail)


def resource_not_found(detail: str | None = None) -> AppError:
    """资源不存在**或**不属于当前用户。

    调用方在两个分支上都要返回它 —— 这正是「不泄漏存在性」的实现方式。
    """
    return AppError(ErrorCode.RESOURCE_NOT_FOUND, detail=detail)
