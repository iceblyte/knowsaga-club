"""健康检查接口。

用于：
1. 前端启动时探测后端可达性；
2. 部署后的存活探针；
3. 排查「模型名 / Key 是否配置正确」（`data.model` 与 `data.key_configured`）。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.response import ok

router = APIRouter(tags=["health"])


@router.get("/health", summary="健康检查")
def health() -> dict:
    """返回服务状态与关键配置摘要（**不返回密钥本身**）。"""
    s = get_settings()
    return ok(
        {
            "status": "healthy",
            "version": s.app_version,
            "env": s.app_env,
            "model": s.deepseek_model,
            "search_enabled": s.knowledge_search_enabled,
            "key_configured": s.has_deepseek_key,
        }
    )
