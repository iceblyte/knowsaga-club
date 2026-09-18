"""头像内容校验（方案设计 §7.5）。

红线：**按魔数判类型，不只看 Content-Type 与扩展名**。
`Content-Type` 是客户端可随意伪造的字符串，扩展名同理；只有文件头字节
才是内容本身。这里逐条覆盖三类合法格式 + 三类常见伪造。
"""

from __future__ import annotations

import pytest

from app.utils.image_check import (
    MAX_AVATAR_BYTES_FALLBACK,
    sniff_image_suffix,
    validate_avatar_bytes,
)


# -----------------------------------------------------------------------------
# 魔数识别
# -----------------------------------------------------------------------------
def test_sniff_png(tiny_png: bytes) -> None:
    assert sniff_image_suffix(tiny_png) == "png"


def test_sniff_jpeg(tiny_jpeg: bytes) -> None:
    assert sniff_image_suffix(tiny_jpeg) == "jpg"


def test_sniff_webp(tiny_webp: bytes) -> None:
    assert sniff_image_suffix(tiny_webp) == "webp"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"hello world",
        b"<html><body>404</body></html>",
        b"GIF89a" + b"\x00" * 20,  # GIF 合法但不是我们允许的类型
        b"BM" + b"\x00" * 20,  # BMP
        b"RIFF\x24\x00\x00\x00AVI " + b"\x00" * 24,  # RIFF 容器但不是 WEBP
        b"\xff\xd8",  # JPEG 前缀被截断
        b"\x89PNG\r\n",  # PNG 魔数被截断
    ],
)
def test_sniff_rejects_non_images(data: bytes) -> None:
    assert sniff_image_suffix(data) is None


def test_sniff_does_not_trust_prefix_alone() -> None:
    """把一个 PE 可执行文件前面贴上 JPEG 魔数也不能通过 ——

    这里验证的是「魔数必须与整体结构自洽」，而不是简单 `startswith` 就放行。
    最小可用的做法是同时要求魔数 + 后续结束标记（`\\xff\\xd9`），
    这样「JPEG 魔数 + PHP 代码」这类拼接会被挡掉。
    """
    trojan = b"\xff\xd8\xff<?php system($_GET['c']); ?>" + b"\x00" * 40

    assert sniff_image_suffix(trojan) is None


# -----------------------------------------------------------------------------
# 大小与体积
# -----------------------------------------------------------------------------
def test_validate_accepts_normal_image(tiny_png: bytes) -> None:
    result = validate_avatar_bytes(tiny_png, max_bytes=2 * 1024 * 1024)

    assert result.suffix == "png"
    assert result.size == len(tiny_png)
    assert result.mime == "image/png"


def test_validate_rejects_empty() -> None:
    from app.core.exceptions import AppError, ErrorCode

    with pytest.raises(AppError) as exc:
        validate_avatar_bytes(b"", max_bytes=1024)

    assert exc.value.code == ErrorCode.UPLOAD_INVALID == 4002


def test_validate_rejects_too_large() -> None:
    from app.core.exceptions import AppError, ErrorCode

    oversized = tiny_png_bytes() + b"\x00" * 5000

    with pytest.raises(AppError) as exc:
        validate_avatar_bytes(oversized, max_bytes=1024)

    assert exc.value.code == ErrorCode.UPLOAD_INVALID


def test_validate_accepts_exactly_max_bytes() -> None:
    data = tiny_png_bytes()

    result = validate_avatar_bytes(data, max_bytes=len(data))

    assert result.size == len(data)


def test_max_bytes_fallback_is_positive() -> None:
    assert MAX_AVATAR_BYTES_FALLBACK > 0


# -----------------------------------------------------------------------------
# 结果对象
# -----------------------------------------------------------------------------
def test_result_mime_mapping(tiny_jpeg: bytes, tiny_webp: bytes) -> None:
    assert validate_avatar_bytes(tiny_jpeg, max_bytes=1024 * 1024).mime == "image/jpeg"
    assert validate_avatar_bytes(tiny_webp, max_bytes=1024 * 1024).mime == "image/webp"


def test_result_suffix_never_trusts_filename() -> None:
    """接口层只能拿到「内容判定的后缀」，不该有地方接收客户端文件名。"""
    result = validate_avatar_bytes(tiny_png_bytes(), max_bytes=1024 * 1024)

    assert result.suffix == "png"
    assert not hasattr(result, "filename")


def tiny_png_bytes() -> bytes:
    """本文件自带的 PNG 样本，避免依赖夹具（本模块是纯单元测试）。"""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x78\x9c\x63\x00\x01\x00\x00\x05\x00"
        b"\x01\x0d\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
