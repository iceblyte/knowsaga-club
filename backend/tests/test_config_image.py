"""题目配图的配置项契约（`add-question-image-generation` 第 1 组）。

为什么值得单独一个测试文件：这一组里有两个数是**外部上限**（`size` 的像素区间、
`embedding_batch_size` 那类「贴住上游限制」的值），还有一组凭据的**合取判据**。
写错任何一个的表现都是静默的：

- `IMAGE_SIZE` 用 `x` 而不是 `*` 分隔 ⇒ 上游 400，生图全挂，但出题链照常成功
  （因为生图失败是**降级**而不是报错），于是「配图一条都没有」会被当成「这次就这样」。
- `image_generation_available` 只看开关不看凭据 ⇒ 前端显示一个点下去必然失败的入口。

数值来源见 `openspec/changes/add-question-image-generation/design.md` 的 D3 / D5 / D7。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

#: 一套**齐备**的配图凭据，供「可用性」用例拼装
FULL_COS_ENV = {
    "COS_SECRET_ID": "AKIDtest-not-real",
    "COS_SECRET_KEY": "test-not-real-secret",
    "COS_REGION": "ap-guangzhou",
    "COS_BUCKET": "knowsaga-1250000000",
}


def _defaults() -> Settings:
    """只读代码里的默认值（断掉仓库根 `.env`，避免被开发者本机配置污染）。"""
    return Settings(_env_file=None)


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """按给定环境变量取一份配置（读取前清缓存）。"""
    from app.core.config import get_settings

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


# ---------------------------------------------------------------- 默认值
def test_image_defaults() -> None:
    """开关默认关闭 + 各项默认值。"""
    s = _defaults()

    # 默认关闭：生图要花钱、要占对象存储，不该在部署方不知情时开始消耗
    assert s.image_generation_enabled is False

    # 默认模型是 z-image-turbo（2026-09-26 换的，原先为 qwen-image-2.0）。
    # 换它的三个理由：① 便宜；② 快（实测 512*512 约 1.4s / 1024*1024 约 3.5s）；
    # ③ 官方写明「图像张数：**固定 1 张**」，与我们「每题一次调用（n=1）+ 并发」
    #    的设计天然契合，不存在「一次多图」那种用不上的能力。
    assert s.image_model == "z-image-turbo"

    # ⚠️ 分隔符必须是 `*`（DashScope 协议），不是 `x`
    assert s.image_size == "512*512"
    assert "*" in s.image_size

    # 并发/超时/预算三者都必须有界
    # 并发默认 **2**（2026-09-26 由 3 下调，design D17）：实测该百炼账号约 2 rps，
    # 「并发 3 必挂 1 个 429」而「并发 2 连跑 4 轮 8 张全过」；且 client **没有重试**，
    # 429 就等于那道题没图 ⇒ 默认值取**验证过的 2**，而不是当初拍脑袋的 3。
    # ⚠️ 别把它理解成「2 是上游硬限制」——那是账号配额，换账号前先重测。
    assert s.image_max_workers == 2
    assert s.image_timeout_seconds > 0
    assert s.image_budget_seconds > s.image_timeout_seconds

    # 每人每天 20 张（需求给定）
    assert s.image_daily_quota == 20

    # 下载上限存在，且是个「单张图」量级的数（不是几百 MB）
    assert 0 < s.image_download_max_bytes <= 32 * 1024 * 1024

    # 关掉上游润色与浮水印：前者会把「与题干匹配」改跑偏，
    # 后者本身就是画面上的文字（与「画面不出现文字」的自我约束冲突）
    assert s.image_prompt_extend is False
    assert s.image_watermark is False

    # 凭据默认全空 —— 模板里必须留空
    assert s.cos_secret_id == ""
    assert s.cos_secret_key == ""
    assert s.cos_region == ""
    assert s.cos_bucket == ""
    assert s.cos_public_base_url == ""


def test_image_size_is_inside_upstream_limits() -> None:
    """`size` 的两个数都要落在上游允许的 512–2048 区间内。

    上游规则（2026-09-25 核对官方 API 参考）：总像素须在 512×512 – 2048×2048 之间。
    越界不是「退化成默认值」，是**直接 400** —— 而它会以「配图全没有」的形式表现。
    """
    size = _defaults().image_size
    w, _, h = size.partition("*")
    assert w.isdigit() and h.isdigit(), f"size 必须形如 `512*512`，当前 {size!r}"
    assert 512 <= int(w) <= 2048
    assert 512 <= int(h) <= 2048


# ---------------------------------------------------------------- 可用性判据
def test_image_unavailable_by_default() -> None:
    """默认（开关关 + 无凭据）不可用。"""
    assert _defaults().image_generation_available is False
    assert _defaults().has_image_credentials is False


def test_image_unavailable_when_switch_off_but_credentials_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """凭据齐备但开关关 ⇒ 仍不可用（开关是总闸）。"""
    s = _settings(
        monkeypatch,
        IMAGE_GENERATION_ENABLED="false",
        DASHSCOPE_API_KEY="sk-fake-for-tests",
        **FULL_COS_ENV,
    )
    assert s.has_image_credentials is True
    assert s.image_generation_available is False


@pytest.mark.parametrize("missing", sorted(FULL_COS_ENV))
def test_image_unavailable_when_cos_field_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """COS 四项缺任意一项 ⇒ 不可用。

    ⚠️ 这条是「不给假入口」的实现点：只要有一项没配，前端就**不显示**开关。
    缺 ID/KEY 传不上去，缺 REGION/BUCKET 拼不出访问地址 —— 两种都必然失败。
    """
    env = {k: v for k, v in FULL_COS_ENV.items() if k != missing}
    env["IMAGE_GENERATION_ENABLED"] = "true"
    env["DASHSCOPE_API_KEY"] = "sk-fake-for-tests"
    # 该字段留空
    env[missing] = ""

    s = _settings(monkeypatch, **env)
    assert s.image_generation_available is False, f"缺少 {missing} 时不该判定为可用"


def test_image_unavailable_without_dashscope_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开、COS 齐，但百炼 key 空 ⇒ 不可用（生图一步都走不了）。"""
    s = _settings(
        monkeypatch,
        IMAGE_GENERATION_ENABLED="true",
        DASHSCOPE_API_KEY="",
        **FULL_COS_ENV,
    )
    assert s.image_generation_available is False


def test_image_available_when_everything_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """四项齐备 + 开关开 + 有百炼 key ⇒ 可用。"""
    s = _settings(
        monkeypatch,
        IMAGE_GENERATION_ENABLED="true",
        DASHSCOPE_API_KEY="sk-fake-for-tests",
        **FULL_COS_ENV,
    )
    assert s.has_image_credentials is True
    assert s.image_generation_available is True


def test_custom_domain_is_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """自定义域名（CDN）**不算**必需项：它有默认拼法。"""
    s = _settings(
        monkeypatch,
        IMAGE_GENERATION_ENABLED="true",
        DASHSCOPE_API_KEY="sk-fake-for-tests",
        COS_PUBLIC_BASE_URL="",
        **FULL_COS_ENV,
    )
    assert s.image_generation_available is True


# ---------------------------------------------------------------- URL 前缀
def test_cos_url_prefix_default_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配自定义域名时按腾讯云默认域名拼。"""
    s = _settings(monkeypatch, COS_PUBLIC_BASE_URL="", **FULL_COS_ENV)
    assert s.cos_url_prefix == "https://knowsaga-1250000000.cos.ap-guangzhou.myqcloud.com"


def test_cos_url_prefix_custom_domain_wins_and_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配了自定义域名就用它，且去掉末尾斜杠（否则拼出来的 key 会多一个 `/`）。"""
    s = _settings(monkeypatch, COS_PUBLIC_BASE_URL="https://img.example.com/", **FULL_COS_ENV)
    assert s.cos_url_prefix == "https://img.example.com"


@pytest.mark.parametrize("blank", ["COS_REGION", "COS_BUCKET"])
def test_cos_url_prefix_empty_when_unbuildable(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """拼不出来的输入 ⇒ 返回空串（调用方据此判定用不了），而不是拼一个坏 URL。"""
    env = dict(FULL_COS_ENV)
    env[blank] = ""
    s = _settings(monkeypatch, COS_PUBLIC_BASE_URL="", **env)
    assert s.cos_url_prefix == ""


# ---------------------------------------------------------------- 可被环境变量覆盖
@pytest.mark.parametrize(
    ("env_key", "env_value", "attr", "expected"),
    [
        ("IMAGE_GENERATION_ENABLED", "true", "image_generation_enabled", True),
        # 覆盖值刻意取一个**与默认值不同**的真实模型，否则这条用例证明不了「覆盖生效」
        ("IMAGE_MODEL", "qwen-image-plus", "image_model", "qwen-image-plus"),
        ("IMAGE_SIZE", "1024*1024", "image_size", "1024*1024"),
        ("IMAGE_MAX_WORKERS", "6", "image_max_workers", 6),
        ("IMAGE_TIMEOUT_SECONDS", "35", "image_timeout_seconds", 35),
        ("IMAGE_BUDGET_SECONDS", "90", "image_budget_seconds", 90),
        ("IMAGE_DAILY_QUOTA", "50", "image_daily_quota", 50),
        ("IMAGE_DOWNLOAD_MAX_BYTES", "1048576", "image_download_max_bytes", 1048576),
        ("IMAGE_PROMPT_EXTEND", "true", "image_prompt_extend", True),
        ("IMAGE_WATERMARK", "true", "image_watermark", True),
    ],
)
def test_image_settings_can_be_overridden_by_env(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    env_value: str,
    attr: str,
    expected: object,
) -> None:
    """部署方要能按自己的额度与耐心调整这些值（代码不用动）。"""
    s = _settings(monkeypatch, **{env_key: env_value})
    assert getattr(s, attr) == expected
