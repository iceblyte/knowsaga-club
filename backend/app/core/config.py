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

    # ---------- 联网检索 ----------
    # 抽象层见 app/llm/search/。开关关 → NoopSearchProvider；开关开但 Provider 未实现、
    # 名字拼错、或 key 为空 → 直接报 5000（**不静默降级成不联网**）。
    # 理由见 docs/MVP开发计划.md §12.1 第 11 条：静默降级最糟 —— 配置明明打开，用户却以为在联网。
    knowledge_search_enabled: bool = False
    knowledge_search_provider: str = "none"
    bocha_api_key: str = ""
    tavily_api_key: str = ""

    # 取材的硬上限（design D5）：多轮工具调用必须有界，否则一次慢请求就能吃掉出题预算。
    search_agent_max_rounds: int = 3
    search_agent_max_tool_calls: int = 4
    search_agent_budget_seconds: int = 20
    # 单次工具调用的超时（design D12）：上游 `langchain-tavily` 的 `requests.post`
    # **没有** timeout（0.2.18 已核源码），网络黑洞会让线程无限等。
    # 独立于 `quiz_timeout_seconds`：那是「整条出题链」的粒度，这里是「一次工具调用」。
    search_tool_timeout_seconds: int = 8
    # ⚠️ **extract 单独一个更长的上限**（2026-09-22 端到端实测追加）。
    # 两个工具的量级完全不同：`tavily_search` 回来的是一小段 JSON 摘要，
    # 而 `tavily_extract` 回来的是**整页正文**（第 0 组实测单页 22,916 / 74,801 字符）。
    # 共用 8s 的后果不是「慢一点」，是**用户贴的链接读不到** —— 实测对 Wikipedia 词条
    # 连续两次撞在 8s 上，而「我贴了链接却没被读」是本产品最不能出现的失败（design D4）。
    # 它能吃掉总预算（`search_agent_budget_seconds=20`）的大半，这是**有意的**：
    # 链接读取是优先级最高的一次取材，让它先跑完，剩下的预算再留给模型自己决定怎么用。
    search_extract_timeout_seconds: int = 15
    # 每次 search 的结果条数。上游把它列为**实例级**参数（调用时传会抛
    # `forbidden_params`），所以只能由服务端定，模型改不了 —— 见 design D2。
    search_max_results: int = 5

    # 资料注入 Prompt 的截断上限（design D14）。实测单页 `raw_content` 可达
    # **74,801** 字符（Wikipedia 词条），而 `quiz_max_tokens` 只有 4096 ——
    # 不截断就会把 Prompt 挤爆，表现是「模型答非所问」而不是报错。
    # 三者关系必须满足 snippet < page < reference（有单测钉住）。
    search_snippet_max_chars: int = 600
    search_page_max_chars: int = 6000
    search_reference_max_chars: int = 12000

    # `country` 的地域偏好（design D3）。官方说明「只在 topic=general 时生效」。
    # 中文输入 → `search_country_default`；英文输入 → `search_country_default_en`。
    # 两者都设 `None` 即完全关掉地区偏好。
    # ⚠️ 空字符串会被解析成 `None`（见 `_blank_country_is_none`），否则 `country=""`
    # 会被原样传给上游 —— 不报错、也不生效，只表现为「地区偏好神秘失效」。
    search_country_default: str | None = "china"
    search_country_default_en: str | None = None

    # ---------- 私有知识库（RAG）----------
    # 抽象层见 app/llm/kb/。开关关掉时：接口一律拒绝、取材链不绑知识库工具、
    # 不加载 chromadb —— 与加入本功能之前逐位一致。
    # **默认关**的理由与 `knowledge_search_enabled` 相同：新能力不该在部署方
    # 不知情的情况下开始吃磁盘与外部 API 额度。
    knowledge_base_enabled: bool = False

    # 向量化用百炼（DashScope）的 text-embedding-v4。
    # 为什么走原生 SDK 而不是 OpenAI 兼容端点：原生接口有 `text_type`
    # （入库传 document、检索传 query），兼容端点没有这个概念，
    # 走它会把这个区分丢掉 —— 而它恰好影响召回质量（design D4）。
    dashscope_api_key: str = ""
    embedding_model: str = "text-embedding-v4"
    # ⚠️ 维度必须固定：collection 建好之后向量维度就锁死了，
    # 改这个值**不会报错**，只会让新写入的向量永远检索不出来。
    # 它会被写进 collection 的元数据，排查时能一眼看出「库是 1024 维建的、现在是 768」。
    embedding_dim: int = 1024
    # 单次请求提交的文本条数。⚠️ 2026-09-24 用真实 key 实测：上游上限**恰为 10**
    # （n=10 通过，n=11 起返 400 `it should not be larger than 10`）
    # ⇒ 这个值是「贴住上限」，**只能调小、不能调大**；超限是整次调用失败而非截断。
    embedding_batch_size: int = 10
    # 单次向量化调用的超时（秒）。上游 SDK 不保证自带超时。
    embedding_timeout_seconds: int = 30

    # 分块（字符数）。中文场景下 500 字约等于一段完整论述；
    # overlap 取 1/10，保证跨块边界的那句话不会被腰斩成两半。
    kb_chunk_size: int = 500
    kb_chunk_overlap: int = 50

    # 检索：取几条。与 `search_max_results` 分开配 —— 网页片段与文档片段的
    # 信息密度不同，共用一个数必然有一方不合适。
    kb_search_top_k: int = 4

    # 上传准入：单文件上限（字节）。20 MB 与原型 05 第 2 屏的文案一致。
    kb_doc_max_bytes: int = 20 * 1024 * 1024
    # 单个知识库的文档数上限。纯防呆：避免一次把解析线程池占死。
    kb_max_docs_per_base: int = 100

    # 解析线程池大小。**独立于出题线程池**（理由同 report_service：
    # 解析不该排在出题任务后面等），固定小规模；池满时**不排队**，
    # 直接把该文档判为失败 —— 解析可以重试，不值得为它把常驻线程撑大。
    kb_parse_workers: int = 2
    # 向量库（Chroma）持久化目录；留空则用 backend/vectorstore。
    # 刻意不放在 uploads 下：那是用户上传目录，混进去会让「清空上传」
    # 这类操作产生连带伤害（design D10）。
    vectorstore_dir: str = ""
    # 文档解析进度的轮询间隔（毫秒）。
    # 原型 05 第 3 屏写的是 8 秒，这里取 2 秒：轮询间隔与「规避小程序 60 秒
    # 请求上限」无关（那个上限约束的是**单次**请求时长），而 8 秒粒度下
    # 用户要空等两轮才看得到状态变化。
    kb_doc_poll_interval_ms: int = 2000

    # ---------- 题目配图（生图 + 对象存储）----------
    # 用户勾选「生成配图」时，出题链会为每道题生成一张与题目内容相关的图片，
    # 转存到腾讯云 COS 之后把**永久 URL** 写进题目（上游返回的临时链接只有 24 小时）。
    # 实现见 app/llm/image/，接链见 app/services/quiz_service.py。
    # 【默认 false】与 `knowledge_search_enabled` / `knowledge_base_enabled` 同一条纪律：
    # 新能力不该在部署方不知情时开始消耗生图额度与对象存储。
    image_generation_enabled: bool = False

    # 生图模型。取 `z-image-turbo`（2026-09-26 由 `qwen-image-2.0` 换过来），三个理由：
    #   ① 便宜、② 快（官方定位「轻量模型，快速生图」；实测 512*512 约 1.4s）；
    #   ③ 官方写明「图像张数：**固定 1 张**」—— 与下面的实现天然契合。
    # ⚠️ 我们**不用** `n>1`：一次调用只带一个 prompt，`n=5` 得到的是同一主题的
    # 5 张近似图，做不到「每道题配与自己相关的图」。实现取「每题一次调用 + 并发」。
    # 与 qwen 系列同属 DashScope 的 `MultiModalConversation` 家族、响应路径一致，
    # 所以换模型不需要改 `llm/image/` 的代码。
    image_model: str = "z-image-turbo"
    # 图片尺寸。⚠️ 分隔符是 **`*`**（DashScope 协议，如 `512*512`），不是 `x`。
    # z-image-turbo 的限制：总像素须落在 [512*512, 2048*2048]，**默认值是 1024*1536**；
    # 官方推荐区间是 [1024*1024, 1536*1536]（原话「出图效果更佳」）。
    # 取 512*512 是**允许的下限**：够用于记忆辅助、更省额度也更快，但清晰度明显低于
    # 推荐区间，想提质量改这里即可（代码不动）。
    image_size: str = "512*512"
    # 并发线程数。与出题链共用进程，**必须有界**（理由同 `_executor` 的注释）。
    image_max_workers: int = 3
    # 单张生图的超时（秒）。生图比检索慢得多，所以比 `search_tool_timeout_seconds` 宽。
    image_timeout_seconds: int = 20
    # 整段生图的**总时间预算**（秒）。超出即放弃剩余图片、直接收尾 ——
    # 与 `quiz_generation_budget_seconds` 同一个理由：宁可少几张图，
    # 也不能让「副本召唤中」空转两分钟。
    image_budget_seconds: int = 45
    # 每人每天可生成的张数。**默认 20**（需求给定）。
    # 落库在 `image_quota_usage` 表上（按业务日 + 用户原子自增），**不复用**
    # `core/ratelimit.py`：那是进程内滑动窗口，重启即清零、多实例各算各的。
    image_daily_quota: int = 20
    # 单张图下载（上游 → 本地内存）的字节上限。超过即判该张失败，
    # 不把一张来路不明的大文件塞进内存再传上云。
    image_download_max_bytes: int = 8 * 1024 * 1024
    # 交给生图模型的负向提示词（可留空）。主要的「不泄题」约束由提示词构建器
    # 以**正向约束**保证（见 app/llm/image/prompt.py 的「画面中不得出现任何文字」）。
    # ⚠️ 别把它读成一道有效护栏：`z-image-turbo` 的官方参数表里**没有** `negative_prompt`
    # （只列了 size / prompt_extend / seed）。实测（2026-09-26）带上它仍返回 200，
    # **但上游是否真的采用它，未经验证** —— 现状是「发了，可能被忽略」。
    image_negative_prompt: str = "文字, 汉字, 字母, 水印, 标志, 低质量, 模糊"
    # 要不要让上游模型自动润色提示词。**默认关**：我们的提示词已经足够具体，
    # 润色会把「与题干匹配」这件事改跑偏。对应请求参数 `prompt_extend`。
    image_prompt_extend: bool = False
    # 是否给生成的图加水印。**默认关** —— 水印是画面上的文字，
    # 与我们「画面不出现文字」的自我约束冲突。
    # ⚠️ 同 `image_negative_prompt`：`z-image-turbo` 官方参数表里没有 `watermark`，
    # 实测带上仍返回 200，**是否被采用未经验证**。
    image_watermark: bool = False

    # 对象存储（腾讯云 COS）。申请：https://console.cloud.tencent.com/cam/capi
    # ⚠️ SecretId / SecretKey 是**密钥**，只允许存在于根 `.env`（已被 gitignore），
    #    `.env.example` 里必须留空。提交前跑 `python tools/scan_secrets.py`。
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    # 地域，形如 `ap-guangzhou`（创建存储桶时选的区域）。
    cos_region: str = ""
    # 存储桶名，**必须带 appid 后缀**，形如 `knowsaga-1250000000`。
    cos_bucket: str = ""
    # 自定义 CDN / 加速域名。留空则按 `https://{bucket}.cos.{region}.myqcloud.com` 拼。
    cos_public_base_url: str = ""

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

    @field_validator("search_country_default", "search_country_default_en", mode="before")
    @classmethod
    def _blank_country_is_none(cls, v: object) -> object:
        """空字符串 → `None`（= 关掉地区偏好）。

        pydantic 对 `str | None` 会把 `""` 校验成 `""` 而不是 `None`，于是 `country=""`
        会被原样交给上游：不报错、也不生效，只表现为「地区偏好神秘失效」。
        而 `.env.example` 里留空占位是最自然的写法，所以这个兜底必须有。
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

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

    # ---------- 知识库派生 ----------
    @property
    def has_embedding_key(self) -> bool:
        """是否已配置向量化凭据。

        ⚠️ 它在**功能开关打开**时必须为真，否则建库链一步都走不了。
        判定放在服务层（而不是这里让服务启动失败）：未开启该功能的部署
        不该被一个用不到的 key 拖住启动。
        """
        return bool(self.dashscope_api_key.strip())

    @property
    def vectorstore_path(self) -> Path:
        """Chroma 持久化目录（绝对路径）。默认 `backend/vectorstore`。"""
        if self.vectorstore_dir.strip():
            return Path(self.vectorstore_dir.strip()).resolve()
        # config.py -> core, app, backend
        return (Path(__file__).resolve().parents[2] / "vectorstore").resolve()

    @property
    def kb_documents_path(self) -> Path:
        """知识库原文件目录。

        ⚠️ 它在 `uploads_path` **之内**但**不参与静态挂载**（只有 `avatars` 那一层
        挂出去了）。文档是用户私有内容，绝不能被匿名 URL 取到（design D10）。
        """
        return self.uploads_path / "kb"

    # ---------- 题目配图派生 ----------
    @property
    def has_image_credentials(self) -> bool:
        """对象存储（COS）凭据是否齐备。

        四项缺一不可：缺 bucket 或 region 拼不出访问地址，缺 SecretId/SecretKey 传不上去。
        `cos_public_base_url`（自定义域名）**不算必需** —— 它有默认拼法。
        """
        return all(
            v.strip()
            for v in (self.cos_secret_id, self.cos_secret_key, self.cos_region, self.cos_bucket)
        )

    @property
    def image_generation_available(self) -> bool:
        """题目配图能力**对外是否可用** —— 前端入口显隐与接口准入的唯一判据。

        ⚠️ 它是「开关 && 凭据齐备」的合取，**不是**只看开关：
        开关打开但缺百炼 key 或 COS 配置时，这里必须是 `False` ——
        否则前端会显示一个点下去必然失败的按钮（红线：不给假入口）。

        百炼 key 与私有知识库的向量化**复用同一个** `DASHSCOPE_API_KEY`
        （同一个账号平台），所以这里读的是同一个字段。
        """
        return (
            self.image_generation_enabled
            and bool(self.dashscope_api_key.strip())
            and self.has_image_credentials
        )

    @property
    def cos_url_prefix(self) -> str:
        """对象存储的公开访问前缀（末尾不含 `/`）。

        配了自定义域名就用它；否则按腾讯云默认域名拼。
        输入不全时返回空串 —— 调用方（`llm/image/store.py`）据此判定「用不了」。
        """
        if self.cos_public_base_url.strip():
            return self.cos_public_base_url.strip().rstrip("/")
        bucket = self.cos_bucket.strip()
        region = self.cos_region.strip()
        if not (bucket and region):
            return ""
        return f"https://{bucket}.cos.{region}.myqcloud.com"

    @property
    def effective_test_database_url(self) -> str:
        """测试库连接串。未配置 TEST_DATABASE_URL 时**不做兜底**——
        退回业务库会让 pytest 的清表操作直接抹掉真实数据，这里必须响亮的失败。"""
        return self.test_database_url.strip()


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例。测试中可调用 `get_settings.cache_clear()` 重置。"""
    return Settings()
