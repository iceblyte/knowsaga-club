"""头像内容校验：按**魔数**判类型。

## 为什么不能信 Content-Type 与扩展名

两者都是客户端说了算的字符串。`("evil.png", b"<?php ... ?>", "image/png")`
这个请求在扩展名与 MIME 两层都是「合法 PNG」，只有内容不是。
所以类型判断必须落到字节本身。

## 为什么还要查「结构收尾标记」

只判前缀的话，`b"\\xff\\xd8\\xff" + 任意内容` 就能通过 —— 攻击者可以把
脚本或可执行体直接拼在图片头后面（polyglot 文件）。加上收尾标记，
拼接体就会被拦下。这不是万无一失的防御（真正的防线是「静态目录不执行脚本
+ 用服务端判定的 Content-Type 响应」），但它把成本最低的那类攻击挡在门外。

## 已知取舍

- JPEG 要求出现 `\\xff\\xd9`（EOI）。**被截断的 JPEG 会被拒** ——
  这是有意的：截断文件本来就是坏图，放进来只会让用户看到破图。
- PNG 要求出现 `IEND`。所有正常 PNG 都有。
- WEBP 只校验 `RIFF....WEBP` 四个标记位，不校验长度字段
  （部分编码器会把长度写成对齐后的值，严格比对会误杀）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import upload_invalid

#: `AVATAR_MAX_BYTES` 未配置时的兜底（方案 §7.5：上限 2 MB）
MAX_AVATAR_BYTES_FALLBACK = 2 * 1024 * 1024

#: 允许的类型 -> MIME。与 `utils/crypto.ALLOWED_IMAGE_SUFFIXES` 同源口径。
_MIME_BY_SUFFIX: dict[str, str] = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_TERMINATOR = b"IEND"
_JPEG_PREFIX = b"\xff\xd8\xff"
_JPEG_TERMINATOR = b"\xff\xd9"
_RIFF_PREFIX = b"RIFF"
_WEBP_MARKER = b"WEBP"


@dataclass(frozen=True, slots=True)
class AvatarValidation:
    """校验通过的结果。

    **只有服务端判定的后缀**，刻意不包含任何来自客户端的文件名 ——
    这样调用方在类型层面就没有「用客户端名字落盘」的机会。
    """

    suffix: str
    mime: str
    size: int


def sniff_image_suffix(data: bytes) -> str | None:
    """按内容判断图片类型；不是允许的图片时返回 `None`。"""
    if not data:
        return None

    if data.startswith(_PNG_SIGNATURE) and _PNG_TERMINATOR in data:
        return "png"

    # 注意从第 3 字节之后找 EOI：前缀本身是 ff d8 ff，其中不含 ff d9，
    # 但从索引 3 开始找语义更清楚（EOI 必须在 SOI 之后）
    if data.startswith(_JPEG_PREFIX) and _JPEG_TERMINATOR in data[len(_JPEG_PREFIX) :]:
        return "jpg"

    if (
        len(data) >= 12
        and data[:4] == _RIFF_PREFIX
        and data[8:12] == _WEBP_MARKER
    ):
        return "webp"

    return None


def validate_avatar_bytes(data: bytes, max_bytes: int | None = None) -> AvatarValidation:
    """校验头像字节流。

    **先判大小、再判内容**：体积检查不依赖内容解析，早失败能避免把
    一个 50 MB 的垃圾全量读进 `sniff` 里做子串查找。

    Raises:
        AppError: 4002（空文件 / 超限 / 内容不是允许的图片）
    """
    limit = MAX_AVATAR_BYTES_FALLBACK if max_bytes is None else int(max_bytes)
    if limit <= 0:
        limit = MAX_AVATAR_BYTES_FALLBACK

    if not data:
        raise upload_invalid(detail="空文件")
    if len(data) > limit:
        raise upload_invalid(detail=f"文件过大：{len(data)} > {limit}")

    suffix = sniff_image_suffix(data)
    if suffix is None:
        raise upload_invalid(detail=f"内容不是允许的图片，前 16 字节={data[:16]!r}")

    return AvatarValidation(suffix=suffix, mime=_MIME_BY_SUFFIX[suffix], size=len(data))
