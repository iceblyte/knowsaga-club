"""API v1 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import health, quiz, tasks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(quiz.router)
api_router.include_router(tasks.router)
