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
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import build_api_router
from app.core.config import get_settings
from app.core.exceptions import AppError, ErrorCode, DEFAULT_MESSAGES
from app.core.logging import get_logger, setup_logging
from app.core.response import fail

logger = get_logger(__name__)

#: 用户上传内容的静态挂载前缀。必须与 `user_service.save_avatar` 里
#: 拼出的 `avatar_url` 一致，否则上传成功但图片打不开。
STATIC_PREFIX = "/static"
AVATARS_MOUNT = f"{STATIC_PREFIX}/avatars"


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
    logger.info("  数据库       : %s", _describe_dsn(s.database_url))
    logger.info(
        "  登录态密钥   : %s",
        "已配置" if s.has_jwt_secret else "**未配置或长度不足 32 字符**",
    )
    logger.info(
        "  微信身份     : %s",
        {
            "mock": "**mock（仅测试）**",
            "real": "已配置凭据" if s.has_wechat_credentials else "**凭据未配置**",
        }[s.wechat_provider],
    )
    logger.info(
        "  调试登录通道 : %s",
        "已挂载 /auth/dev" if (s.is_dev and s.dev_login_enabled) else "未挂载",
    )
    logger.info("  上传目录     : %s", s.uploads_path)
    if not s.has_deepseek_key:
        logger.warning("未检测到 DEEPSEEK_API_KEY，出题接口将直接失败。请在仓库根目录的 .env 中填写。")
    if not s.has_jwt_secret:
        # 这是**配置错误**：宁可启动时就吵，也不要等第一个用户登录时才发现
        logger.error(
            "JWT_SECRET 未配置或长度不足 32 字符，登录接口会失败。"
            '生成方式：python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    logger.info("=" * 68)
    yield
    logger.info("知拾冒险社 · 后端已停止")


def _describe_dsn(dsn: str) -> str:
    """只打印「是否配置 + 主机/库名」，**绝不打印密码**。

    启动日志经常被贴进 issue。`DATABASE_URL` 里含密码，
    哪怕是调试也要先把凭证摘掉。
    """
    raw = (dsn or "").strip()
    if not raw:
        return "**未配置**"
    try:
        from urllib.parse import urlparse

        parsed = urlparse(raw)
        host = parsed.hostname or "?"
        port = parsed.port or 3306
        database = (parsed.path or "/").lstrip("/") or "?"
        return f"{parsed.scheme}://{host}:{port}/{database}"
    except Exception:  # noqa: BLE001 - 日志函数绝不因此抛错
        return "已配置（无法解析）"


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

    app.include_router(build_api_router(), prefix="/api/v1")

    # ---------- 静态资源：用户上传的头像 ----------
    # 为什么在 create_app 里建目录：StaticFiles 默认 check_dir=True，
    # 目录不存在会直接抛错，让「第一次部署忘了建目录」变成一个启动失败。
    # 挂载点只覆盖 avatars 子目录（而不是整个 uploads），
    # 未来若新增别的上传类型，不会因为挂在上一层而意外对外暴露。
    avatars_dir = settings.avatars_path
    avatars_dir.mkdir(parents=True, exist_ok=True)
    app.mount(AVATARS_MOUNT, StaticFiles(directory=str(avatars_dir)), name="avatars")

    return app


app = create_app()
