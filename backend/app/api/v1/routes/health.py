"""健康检查接口。

用于：
1. 前端启动时探测后端可达性；
2. 部署后的存活探针；
3. 排查「模型名 / Key 是否配置正确」（`data.model` 与 `data.key_configured`）；
4. 下发**功能开关 / 能力**给前端 —— `data.knowledge_base_enabled`（私有知识库开关）
   与 `data.image_generation_enabled`（题目配图能力）。
   两者都是「要不要让用户看见这个功能」的唯一事实来源（design D18 / D7）：
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
            # 题目配图的**能力**（不是裸开关）：要「开关打开 + 百炼 key + COS 五项齐全」
            # 三者同时成立才为真。下发裸开关会出现「true 但缺凭据」⇒ 前端显示开关 ⇒
            # 用户点下去必然失败。宁可少一个入口，也不给一个点了必失败的按钮（design D7）。
            # 它同样**不是权限位**，但别读成「关掉也能用」：生图没有独立端点
            # （请求走既有的 `POST /quiz/generate` + `generate_images`），开关只改变
            # 「入口可见性」与「带 generate_images=true 的请求是否被用例层 4001 拒掉」，
            # 不改变任何路由的注册状态、也不会 403。
            "image_generation_enabled": s.image_generation_available,
            "key_configured": s.has_deepseek_key,
        }
    )
