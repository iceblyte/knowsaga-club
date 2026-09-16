"""应用配置：统一从仓库根目录的 `.env` 读取。

设计要点：
- 使用 pydantic-settings 的 `SettingsConfigDict`，允许大写环境变量名直接映射。
- `env_file` 指向 **仓库根目录** 的 `.env`（backend/ 的上一级），而不是 backend/.env，
  这样前后端与脚本共用同一份密钥，不会出现「两个 .env 不一致」的问题。
- `.env` 已被 .gitignore 忽略；仓库内只提交 `.env.example` 作为模板。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[0]=core, [1]=app, [2]=backend, [3]=仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    """全局配置。字段名小写，通过大小写不敏感匹配 .env 中的大写键。"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_env: Literal["dev", "prod"] = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "*"
    app_version: str = "0.1.0"

    # ---------- DeepSeek ----------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_model_pro: str = "deepseek-v4-pro"
    deepseek_use_beta: bool = False
    # deepseek-flash 默认开启思考模式，会导致 content 为空且强制 tool_choice 报 400。
    # 出题/报告链必须关闭，见 docs/MVP开发计划.md §2.4.1。
    deepseek_thinking: bool = False
    deepseek_reasoning_effort: Literal["low", "medium", "high"] = "medium"

    # ---------- 出题链参数 ----------
    quiz_temperature: float = 0.4
    quiz_top_p: float = 0.9
    quiz_timeout_seconds: int = 30
    quiz_max_tokens: int = 4096
    quiz_max_retries: int = 2
    # 整条兜底阶梯的**总时间预算**（秒）。超出后不再发起剩余尝试，直接进 5001。
    # 为什么需要它：单次尝试的 timeout(30s) × (1 + max_retries(2)) 叠上 HTTP 层重试，
    # 最坏情况会远超用户愿意盯着「副本召唤中」等待的长度。宁可快速失败让用户重试，
    # 也不要让进度条空转两分钟。0 表示只允许第一次尝试（不会变成永远失败的死路）。
    quiz_generation_budget_seconds: int = 50

    # ---------- 报告链参数 ----------
    report_temperature: float = 0.5
    report_top_p: float = 0.9
    report_timeout_seconds: int = 30
    report_max_tokens: int = 2048
    report_max_retries: int = 2

    # ---------- 结构化输出策略 ----------
    # 主通道 = json_mode，降级通道 = function_calling。
    # 为什么不用 function_calling 打头（最初的设计）：实测量化后调换，见 docs/MVP开发计划.md §2.4.1。
    #   - 一次通过率：json_mode 6/6 = 100%，function_calling 4/6 = 67%
    #     （两者失败形态不同：json_mode 是空响应，function_calling 是「模型系统性省略
    #      每题的 knowledge_point / difficulty」——工具调用的参数生成更容易漏嵌套字段）
    #   - json_mode 的代价是 prompt 必须含 "json" 字样与 JSON 示例，quiz_prompt 已满足
    # 保留 function_calling 作降级而不是删掉：两通道**失效原因不同**，
    # 若上游某天不支持 response_format=json_object，只有换通道能救。
    structured_output_primary: Literal["function_calling", "json_mode"] = "json_mode"
    structured_output_fallback: Literal["function_calling", "json_mode"] = "function_calling"

    # ---------- 联网检索（MVP 关闭，仅保留抽象层）----------
    knowledge_search_enabled: bool = False
    knowledge_search_provider: str = "none"
    bocha_api_key: str = ""
    tavily_api_key: str = ""

    # ---------- 异步任务 ----------
    quiz_task_ttl_seconds: int = 600
    quiz_task_poll_interval_ms: int = 1200

    # ---------- 微信（MVP 不使用，预留）----------
    wechat_appid: str = ""
    wechat_app_secret: str = ""

    # ---------- 校验与派生 ----------
    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置解析为列表。"""
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_base_url(self) -> str:
        """`DEEPSEEK_USE_BETA=true` 时切到 beta 端点（官方标注为不稳定特性）。"""
        base = self.deepseek_base_url.rstrip("/")
        if self.deepseek_use_beta:
            return f"{base}/beta"
        return base

    @property
    def has_deepseek_key(self) -> bool:
        """是否已配置可用的 API Key。"""
        return bool(self.deepseek_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例。测试中可调用 `get_settings.cache_clear()` 重置。"""
    return Settings()
