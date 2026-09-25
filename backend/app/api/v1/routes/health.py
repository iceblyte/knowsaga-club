"""健康检查接口。

用于：
1. 前端启动时探测后端可达性；
2. 部署后的存活探针；
3. 排查「模型名 / Key 是否配置正确」（`data.model` 与 `data.key_configured`）；
4. 下发**功能开关**给前端 —— 目前是 `data.knowledge_base_enabled`。
   它是「要不要让用户看见私有知识库」的唯一事实来源（design D18）：
   入口显隐由前端承担，但值由后端给，避免前后端各配一份而漂移。
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
            # 私有知识库的总开关。它**不是**权限 —— `/kb/*` 路由无条件注册
            # （design D18），关掉时接口照样能调；它管的是「要不要让用户看见」，
            # 前端据此决定四处入口（工坊两行 / 我的 / 大厅 chip）显不显示。
            "knowledge_base_enabled": s.knowledge_base_enabled,
            "key_configured": s.has_deepseek_key,
        }
    )
