"""用户输入清洗与校验。

用户从输入框拿到的是「脏」文本：全角空格、零宽字符、粘贴带入的控制字符、
多余的空行。这些直接送进 Prompt 会：
- 污染题干长度统计（零宽字符肉眼不可见但占位）
- 让题量/字数约束失准
- 引入不可见字符导致 JSON 解析异常

清洗管道（顺序不可调换）：

    控制字符剔除 → 换行归一(\\r\\n→\\n) → 类空格字符归一(\\t/全角空格→半角) → 空白段折叠 → 去首尾空白

空白段折叠规则：
- 段内**含 ≥2 个换行** → 折叠为单个 `\\n`（保留段落结构）
- 其余空白段 → 折叠为单个空格
"""

from __future__ import annotations

import re

from app.core.exceptions import invalid_input

# 原型约定：按钮在 8 字激活，计数器上限 200
MIN_INPUT_LEN = 8
MAX_INPUT_LEN = 200

# 零宽字符：肉眼不可见，但会污染长度与 JSON
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")

# C0 控制字符（排除 \x09=TAB、\x0a=LF）+ C1 控制字符
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# 需要归一为半角空格的类空格字符（TAB、不换行空格、各种 Unicode 空格、全角空格）
_SPACE_LIKE = re.compile(r"[\t\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]")

# 待折叠的空白段（换行与空格混合；此时 TAB 与其他 Unicode 空格已被归一为半角空格）
_WHITESPACE_RUN = re.compile(r"[ \n]+")


def strip_control_chars(text: str) -> str:
    """剔除零宽字符与控制字符，保留 `\\n` 与 `\\t`。"""
    if not text:
        return ""
    return _CONTROL.sub("", _ZERO_WIDTH.sub("", text))


def _collapse_run(match: re.Match[str]) -> str:
    """空白段折叠：含 ≥2 个换行视为段落分隔，否则视为普通空白。"""
    run = match.group(0)
    return "\n" if run.count("\n") >= 2 else " "


def normalize_whitespace(text: str) -> str:
    """归一空白：类空格字符转半角、空白段折叠、去首尾空白。"""
    if not text:
        return ""
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    s = _SPACE_LIKE.sub(" ", s)
    s = _WHITESPACE_RUN.sub(_collapse_run, s)
    return s.strip()


def clean_input(text: str, *, truncate: bool = True) -> str:
    """完整清洗管道。

    Args:
        text: 原始用户输入。
        truncate: 为 True（默认）时把结果截断到 `MAX_INPUT_LEN`，
            保证下游（Prompt）拿到的长度永远可控。

    Returns:
        清洗后的文本；输入为空时返回空字符串。
    """
    if not text:
        return ""

    cleaned = strip_control_chars(text)
    cleaned = normalize_whitespace(cleaned)

    if truncate and len(cleaned) > MAX_INPUT_LEN:
        cleaned = cleaned[:MAX_INPUT_LEN].rstrip()

    return cleaned


def validate_input(text: str) -> str:
    """清洗并校验长度，不合规直接抛 `AppError(4001)`。

    **长度按清洗后的文本计算** —— 用空白凑长度不算数。

    Raises:
        AppError: code=4001，内容过短或过长。
    """
    cleaned = clean_input(text, truncate=False)
    length = len(cleaned)

    if length < MIN_INPUT_LEN:
        raise invalid_input(
            f"内容太短啦，再多说一点吧（至少 {MIN_INPUT_LEN} 个字）",
            detail=f"len={length} < {MIN_INPUT_LEN}",
        )

    if length > MAX_INPUT_LEN:
        raise invalid_input(
            f"内容有点长，精简一下再试试（最多 {MAX_INPUT_LEN} 个字）",
            detail=f"len={length} > {MAX_INPUT_LEN}",
        )

    return cleaned
