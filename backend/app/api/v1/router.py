"""API v1 路由汇总。

## 为什么是工厂函数而不是模块级单例

调试通道（`/auth/dev`）**只在开发环境 + 显式开启时注册**。如果路由在
模块导入时就组装好，那么「配置改了」对已经导入的模块毫无影响 ——
测试里就会出现「明明把开关关了，端点还在」这种最坏情况
（一个能免密登录的端点被误认为已关闭）。

改成每次调用都重新组装，判定发生在**建应用的那一刻**，
配置永远是当前值。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    attempts,
    auth,
    health,
    kb,
    quiz,
    report,
    review,
    tasks,
    users,
)
from app.core.config import get_settings


def build_api_router() -> APIRouter:
    """组装 `/api/v1` 下的全部路由（每次调用都是一份新的）。"""
    router = APIRouter()

    router.include_router(health.router)
    router.include_router(auth.router)
    router.include_router(users.router)
    router.include_router(quiz.router)
    router.include_router(tasks.router)
    router.include_router(attempts.router)
    router.include_router(report.router)
    router.include_router(review.router)
    # 知识库**无条件注册**，不像 `auth.dev_router` 那样挂在开关上：
    # `KNOWLEDGE_BASE_ENABLED` 管的是「要不要付 chromadb 的加载代价」
    # （`app/llm/kb/store.py` 里是惰性导入），不是「这些端点存不存在」。
    # 若按开关注册，关掉开关时前端拿到的是 404，与「接口写错了」长得一样；
    # 而「未配向量化凭据」这种情况本来就有一条更准的返回
    # （上传后文档落到 `failed`，文案说明服务暂不可用，见 kb_service）。
    router.include_router(kb.router)

    settings = get_settings()
    if settings.is_dev and settings.dev_login_enabled:
        # 两个条件同时满足才挂载；否则该路径根本不存在（404）
        router.include_router(auth.dev_router)

    return router
