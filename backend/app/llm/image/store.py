"""把生出来的图片转存到腾讯云 COS，并给出**永久**地址。

## 为什么必须转存

上游（百炼）返回的图片链接**只有 24 小时有效期**，官方原话「请及时下载并保存图像」。
而题目是永久保存的：不转存的话，用户第二天回看历史卷轴只会看到一片裂图，
并且没有任何提示 —— 那是本功能最难看的一种失败。所以「下载 → 上传 → 换永久 URL」
是必需步骤，不是性能优化（design D5）。

## 为什么只存 URL 不存图片

图片是二进制且体积大，塞进 `questions` 会让「每道题一行」的热表迅速膨胀，
而 MySQL 本来就不适合当对象存储。数据库里只留一列 `image_url`。

## 对象键为什么用「本次运行的随机短串」而不是卷轴 id

生成发生在**落库之前**（题目要带着图一起落库），那时数据库 id 还不存在，
拿不到 `quiz_id`。所以用一个每次运行生成一次的短串做目录：

    questions/{run_token}/{seq}.{ext}

`run_token` 由编排层生成（`app/llm/image/__init__.py`），同一局的题目落在同一目录下，
便于按局排查；不同局之间不会互相覆盖。

## 桶权限

用默认域名（`https://{bucket}.cos.{region}.myqcloud.com`）时，桶权限需要设为
**公有读**，否则客户端拿不到图（签名 URL 会过期，与本功能「永久地址」的前提冲突）。
这一点写进了 `.env.example` 的 COS 段落。
"""

from __future__ import annotations

import re

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: 对象键里 `run_token` 允许的字符。**刻意只留字母数字与 `_` / `-`**：
#: 允许 `.` 或 `/` 会让 `../../` 这种输入活下来 —— COS 的对象键是扁平字符串，
#: 但键会直接拼进公开 URL，路径语义由客户端与 CDN 决定，不该把这个解释权交出去。
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_-]")

#: 扩展名部分只留字母数字与点。
_SAFE_EXT = re.compile(r"[^A-Za-z0-9.]")

#: 传给 COS SDK 的 HTTP 超时（秒）。上传单张几百 KB 的图，60 秒足够；
#: 不给超时的话网络黑洞会让出题线程一直挂着（与其它上游调用同一条纪律）。
UPLOAD_TIMEOUT_SECONDS = 60


class ImageStoreError(RuntimeError):
    """转存失败。与 `ImageGenError` 一样刻意不抛 `AppError`（后台线程无请求上下文）。"""


def build_object_key(*, run_token: str, seq: int, ext: str) -> str:
    """拼对象键：`questions/{run_token}/{seq}.{ext}`。"""
    safe_token = _SAFE_TOKEN.sub("", str(run_token))[:32] or "run"
    safe_ext = _SAFE_EXT.sub("", ext if ext.startswith(".") else f".{ext}") or ".jpg"
    return f"questions/{safe_token}/{int(seq)}{safe_ext}"


def public_url(key: str, settings: Settings) -> str:
    """把对象键拼成公开访问地址。"""
    prefix = settings.cos_url_prefix
    if not prefix:
        raise ImageStoreError("对象存储的访问前缀为空（缺 COS_BUCKET / COS_REGION）")
    return f"{prefix}/{key.lstrip('/')}"


def _build_client(settings: Settings):  # noqa: ANN202 - CosS3Client，惰性导入故不注解
    """构造 COS 客户端。

    ⚠️ **独立成一个函数是为了让测试能替身它** —— 单测不允许真的上传到云上。
    """
    # 惰性导入：不开这个功能就完全不加载 SDK
    from qcloud_cos import CosConfig, CosS3Client

    config = CosConfig(
        Region=settings.cos_region.strip(),
        SecretId=settings.cos_secret_id.strip(),
        SecretKey=settings.cos_secret_key.strip(),
        Scheme="https",
        Timeout=UPLOAD_TIMEOUT_SECONDS,
    )
    return CosS3Client(config)


def upload_image(
    data: bytes,
    *,
    key: str,
    content_type: str,
    settings: Settings,
) -> str:
    """上传字节流，返回**永久**访问地址。

    Raises:
        ImageStoreError: 凭据不全、上传失败、或拼不出公开地址。
    """
    if not settings.has_image_credentials:
        raise ImageStoreError("对象存储凭据不齐（缺 COS_SECRET_ID/KEY/REGION/BUCKET）")
    if not data:
        raise ImageStoreError("待上传的图片是空的")

    bucket = settings.cos_bucket.strip()
    try:
        client = _build_client(settings)
        client.put_object(
            Bucket=bucket,
            Body=data,
            Key=key,
            ContentType=content_type,
        )
    except Exception as exc:  # noqa: BLE001 - 上游/网络异常一律归一
        raise ImageStoreError(f"{type(exc).__name__}: {exc}") from exc

    return public_url(key, settings)
