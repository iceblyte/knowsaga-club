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

#: JWT 密钥的最低长度。低于它宁可让服务启动失败，也不用弱密钥兜底
#: —— 弱密钥被爆破等于所有人都能伪造任意用户身份。
JWT_SECRET_MIN_LEN = 32


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
    # 报告链的总时间预算（秒）。语义与 `quiz_generation_budget_seconds` 相同，
    # 但**不可省略**，理由与报告链的定位有关：
    # 报告全失败会**降级成模板报告**（不像出题链那样报错），也就是说「超预算」
    # 在这里不会表现为失败，而是表现为「用户拿到的报告话术一直很模板」。
    # 没有一个明确的预算，这类降级会安静地发生很久而无人察觉。
    report_generation_budget_seconds: int = 40

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

    # ---------- 微信（用户系统必需）----------
    # APPID 是公开标识符；APP_SECRET 是真正的密钥，只允许存在于服务端。
    # 两者都为空时登录接口会以 5032 失败（而不是崩溃），便于核心闭环先行联调。
    wechat_appid: str = ""
    wechat_app_secret: str = ""
    #: code2Session 的连接与读取超时（秒）。上游抖动时不能把请求线程挂死。
    wechat_timeout_seconds: int = 8
    #: 身份校验实现。默认 `real`（生产安全）；测试环境必须显式设为 `mock`，
    #: 否则任何走登录接口的用例都会真的去请求微信服务器。
    wechat_provider: Literal["real", "mock"] = "real"

    # ---------- 数据库（同步 PyMySQL）----------
    # 为什么同步而不是异步：本项目接口全是同步 def，出题/报告链还跑在后台线程里。
    # 同步驱动在两条路径上都能直接用，异步则需要事件循环桥接。
    database_url: str = ""
    test_database_url: str = ""

    # ---------- 登录态 ----------
    #: 必填且 ≥ 32 字符；缺失或过短时服务**拒绝启动**（绝不用默认弱密钥兜底）。
    jwt_secret: str = ""
    #: 有效期（小时）。默认 7 天，覆盖「一周回来一次」的典型回访节奏。
    jwt_expire_hours: int = 168

    # ---------- 业务时区 ----------
    #: 「今天」「连续天数」「错题到期」都按此时区判定（见方案设计 §8.7）。
    app_timezone: str = "Asia/Shanghai"

    # ---------- 开发调试登录通道 ----------
    #: 为 true **且** app_env=dev 时才注册 /auth/dev；否则该路由根本不存在。
    dev_login_enabled: bool = False

    # ---------- 登录限流 ----------
    #: 同一来源 IP 在窗口内允许的登录次数。登录是「换个 code 就能新建账号」的入口，
    #: 不限流等于把建档能力开放给脚本。
    login_rate_limit: int = 20
    login_rate_window_seconds: int = 60

    # ---------- 头像上传 ----------
    #: 单文件大小上限（字节），默认 2 MB。
    avatar_max_bytes: int = 2 * 1024 * 1024
    #: 上传根目录；留空则用 backend/uploads。
    uploads_dir: str = ""

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

    # ---------- 用户系统派生 ----------
    @property
    def is_dev(self) -> bool:
        """是否为开发环境。调试登录通道要求它同时为真。"""
        return self.app_env == "dev"

    @property
    def has_jwt_secret(self) -> bool:
        """密钥是否达到可用的最低强度（≥32 字符）。"""
        return len(self.jwt_secret.strip()) >= JWT_SECRET_MIN_LEN

    @property
    def has_wechat_credentials(self) -> bool:
        """微信平台凭据是否齐备（测试号无法换取身份，所以两个都要有）。"""
        return bool(self.wechat_appid.strip()) and bool(self.wechat_app_secret.strip())

    @property
    def uploads_path(self) -> Path:
        """上传根目录（绝对路径）。默认 `backend/uploads`。"""
        if self.uploads_dir.strip():
            return Path(self.uploads_dir.strip()).resolve()
        # config.py -> core, app, backend
        return (Path(__file__).resolve().parents[2] / "uploads").resolve()

    @property
    def avatars_path(self) -> Path:
        """头像目录。"""
        return self.uploads_path / "avatars"

    @property
    def effective_test_database_url(self) -> str:
        """测试库连接串。未配置 TEST_DATABASE_URL 时**不做兜底**——
        退回业务库会让 pytest 的清表操作直接抹掉真实数据，这里必须响亮的失败。"""
        return self.test_database_url.strip()


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例。测试中可调用 `get_settings.cache_clear()` 重置。"""
    return Settings()
