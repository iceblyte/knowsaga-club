"""由标识派生稳定值：昵称后缀、上传文件名、内容指纹。

**这里不放任何「加密保存敏感数据」的能力。** 本轮不存在需要落库的敏感信息
（`session_key` 已确认不落库），所以不需要引入一把自管的加密密钥 ——
不存即没有泄漏面。将来真要做手机号解密时，那属于一次独立的设计，
而不是在这里悄悄加一个函数。

`cryptography` 依然是必需依赖，但它的用途是 **MySQL 9 的
`caching_sha2_password` 认证**（见 docs/用户系统方案设计文档.md §2.2），
与这里的函数无关。
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time

#: 允许的图片后缀 -> MIME 类型。**只用于生成文件名与响应头**，
#: 真正的合规判断靠魔数（见 `app/utils/image_check.py`）。
ALLOWED_IMAGE_SUFFIXES: dict[str, str] = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

#: 预置头像键（与 `users.avatar_key` 的注释、前端 6 个精灵一一对应）
AVATAR_KEYS: tuple[str, ...] = (
    "apprentice",
    "scholar",
    "knight",
    "mage",
    "ranger",
    "artisan",
)

#: 默认头像。原型「冒险者档案」里的学者形象。
DEFAULT_AVATAR_KEY = "scholar"

#: 昵称前缀。与原型「冒险者 · 拾光」同一句式。
NICKNAME_PREFIX = "冒险者"

#: 昵称长度上限，与 `users.nickname VARCHAR(32)` 一致。
#: 界面上按「1–16 字符」提示，留出足够余量给将来的后缀。
NICKNAME_MAX_LEN = 32


def derive_nickname(identity: str, *, prefix: str = NICKNAME_PREFIX) -> str:
    """由稳定标识派生默认昵称，形如「冒险者 · 7A3F」。

    为什么用派生而不是随机：同一用户在任何设备上重新建档都会得到同一个昵称，
    不会出现「重装后昵称变了」这种让人困惑的现象。

    取 sha256 前 2 字节转 4 位大写十六进制 —— 65536 种取值。昵称**不是唯一键**
    （`users` 上只有 `openid` 唯一），所以允许碰撞，不需要重试。
    """
    digest = hashlib.sha256((identity or "").encode("utf-8")).hexdigest()
    suffix = digest[:4].upper()
    return f"{prefix} · {suffix}"


#: 昵称里不允许出现的字符：控制字符、零宽字符、方向控制符。
#:
#: 为什么要拦零宽字符与方向控制符：它们肉眼不可见，却能让「小明」与
#: 「小​明」变成两个看起来完全一样的昵称，用于冒充。这类字符在
#: 用户内容是高频滥用手法，属于必须拦的一类，而不是可选的美化。
_INVISIBLE_RE = re.compile(
    r"[\u0000-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]"
)


class NicknameError(ValueError):
    """昵称不合规。上层转成 4001。"""


def normalize_nickname(raw: str, *, max_len: int = NICKNAME_MAX_LEN) -> str:
    """清洗并校验昵称。

    Args:
        raw: 用户输入。
        max_len: 长度上限。默认用**数据库列的上限**（32）；界面提示的口径更严
            （16，见 `core.constants.NICKNAME_UI_MAX_LEN`），由调用方传入。
            列上限与界面口径分开，是为了让「放宽界面提示」不必改表结构。

    Returns:
        去掉首尾空白与不可见字符后的昵称。

    Raises:
        NicknameError: 为空、超长或含不可见字符。
    """
    if not isinstance(raw, str):
        raise NicknameError("昵称必须是文本")

    if _INVISIBLE_RE.search(raw):
        raise NicknameError("昵称不能包含不可见字符")

    cleaned = raw.strip()
    if not cleaned:
        raise NicknameError("昵称不能为空")
    if len(cleaned) > max_len:
        raise NicknameError(f"昵称最多 {max_len} 个字符")
    return cleaned


def new_avatar_filename(user_id: int, suffix: str) -> str:
    """生成服务端头像文件名。

    **绝不使用客户端提供的文件名**：那是一个能拼出 `../` 的输入，
    轻则覆盖他人文件，重则写到目录之外。

    形状：`u{user_id}_{秒级时间戳}_{6 位随机}.{后缀}`
    - 带 user_id：便于人工排查「这张图是谁的」，但不作为权限依据
      （权限靠登录态，不靠文件名猜）
    - 带随机段：同一用户连续更换头像不会互相覆盖，且文件名不可枚举
    """
    ext = (suffix or "").lower().lstrip(".")
    if ext not in ALLOWED_IMAGE_SUFFIXES:
        ext = "jpg"
    stamp = int(time.time())
    rand = secrets.token_hex(3)
    return f"u{int(user_id)}_{stamp}_{rand}.{ext}"


def content_fingerprint(text: str) -> str:
    """资料内容的指纹（sha256 hex）。

    用途是「同一份资料不重复建卷轴」。**不是安全机制** ——
    它只做归一化后的去重（去首尾空白、压缩内部空白），
    所以不引入盐值，也不需要抗碰撞性以外的东西。
    """
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def guess_suffix_from_mime(mime: str) -> str:
    """由 MIME 猜一个后缀（仅用于回退，不作为合规依据）。"""
    for suffix, known in ALLOWED_IMAGE_SUFFIXES.items():
        if known == (mime or "").lower().strip():
            return suffix
    return "jpg"
