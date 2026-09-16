"""日志配置。

- 统一格式，带毫秒时间戳与 logger 名，便于排查 LLM 调用耗时。
- **自动脱敏**：任何形如 `sk-xxx` 的 API Key 都会在写入日志前被替换为 `sk-***`。
"""

from __future__ import annotations

import logging
import re
import sys

from app.core.config import get_settings

_configured = False

# 匹配 sk- 开头的密钥（DeepSeek / OpenAI 风格）
_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_\-]{4,}\b")
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{4,}", re.IGNORECASE)


class SecretRedactor(logging.Filter):
    """把日志里的密钥替换成掩码，防止密钥泄漏到日志文件。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True

        redacted = _KEY_PATTERN.sub("sk-***", msg)
        redacted = _BEARER_PATTERN.sub(r"\1***", redacted)

        if redacted != msg:
            # 清掉 args，否则格式化时会重复套用
            record.msg = redacted
            record.args = ()

        if record.exc_text:
            record.exc_text = _KEY_PATTERN.sub("sk-***", record.exc_text)
        return True


def setup_logging(level: str | None = None) -> None:
    """初始化根 logger。重复调用是安全的（幂等）。"""
    global _configured
    if _configured:
        return

    settings = get_settings()
    log_level = (level or settings.log_level).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)-28s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    handler.addFilter(SecretRedactor())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # 第三方库降噪
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel("WARNING")

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取带脱敏能力的 logger。"""
    setup_logging()
    logger = logging.getLogger(name)
    if not any(isinstance(f, SecretRedactor) for f in logger.filters):
        logger.addFilter(SecretRedactor())
    return logger
