"""统一响应体：`{code, message, data}`。

所有接口（含错误）都返回这个形状，前端只需判断 `code == 0`。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.exceptions import ErrorCode

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应结构。"""

    code: int = Field(default=int(ErrorCode.OK), description="0 表示成功，非 0 为业务错误码")
    message: str = Field(default="ok", description="人类可读的提示，可直接展示")
    data: T | None = Field(default=None, description="业务数据；失败时为 null")


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应。"""
    return {"code": int(ErrorCode.OK), "message": message, "data": data}


def fail(code: ErrorCode | int, message: str, data: Any = None) -> dict[str, Any]:
    """失败响应。"""
    return {"code": int(code), "message": message, "data": data}
