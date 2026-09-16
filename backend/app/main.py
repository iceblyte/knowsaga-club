"""FastAPI 应用入口。

启动（在 backend/ 目录下）：
    .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError, ErrorCode, DEFAULT_MESSAGES
from app.core.logging import get_logger, setup_logging
from app.core.response import fail

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动/关闭钩子：打印关键配置摘要，便于一眼看出环境是否配错。"""
    s = get_settings()
    setup_logging()
    logger.info("=" * 68)
    logger.info("知拾冒险社 · 后端启动")
    logger.info("  env          : %s", s.app_env)
    logger.info("  version      : %s", s.app_version)
    logger.info("  model        : %s", s.deepseek_model)
    logger.info("  base_url     : %s", s.effective_base_url)
    logger.info("  thinking     : %s", "开启" if s.deepseek_thinking else "关闭（推荐）")
    logger.info("  api key      : %s", "已配置" if s.has_deepseek_key else "**未配置**")
    logger.info("  联网检索     : %s", "开启" if s.knowledge_search_enabled else "关闭")
    if not s.has_deepseek_key:
        logger.warning("未检测到 DEEPSEEK_API_KEY，出题接口将直接失败。请在仓库根目录的 .env 中填写。")
    logger.info("=" * 68)
    yield
    logger.info("知拾冒险社 · 后端已停止")


def create_app() -> FastAPI:
    """工厂函数，便于测试中构造独立实例。"""
    settings = get_settings()
    setup_logging()

    app = FastAPI(
        title="知拾冒险社 API",
        description="把资料变成一场冒险 —— 导入卷轴，AI 出题，答题闯关，生成冒险日志。",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- 全局异常处理：一律返回 {code, message, data} ----------
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.detail:
            logger.warning("AppError code=%s detail=%s", exc.code, exc.detail)
        return JSONResponse(
            status_code=exc.http_status,
            content=fail(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 把 pydantic 的首条错误转成可读提示
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query"))
        detail = f"{loc}: {first.get('msg', '')}".strip(": ")
        logger.warning("参数校验失败 %s", detail)
        return JSONResponse(
            status_code=400,
            content=fail(
                ErrorCode.INVALID_PARAM,
                DEFAULT_MESSAGES[ErrorCode.INVALID_PARAM],
                data=None if not detail else {"field": detail},
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未捕获异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content=fail(ErrorCode.INTERNAL_ERROR, DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR]),
        )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
