"""内容安全过滤。

两层防护：

1. **词表拦截** —— 违规话题直接拒绝，避免无谓的模型调用（省钱 + 合规）。
2. **提示词注入拦截** —— LLM 应用特有的风险：用户输入里夹带"忽略之前的指令"之类，
   试图劫持模型行为、套出系统提示词，或绕过出题约束。

## 白名单机制

白名单按「整条短语豁免」生效。做法是先把白名单短语替换成等长占位符，再扫描词表，
这样「色情图片识别」（正当的图像分类话题）不会被「色情」误伤，
而短语之外单独出现的该词仍会被拦截。

## 关于词表

本文件的词表是**演示级**的最小集合，仅用于验证链路与错误码。
正式上线应替换为专业内容安全服务（如微信内容安全接口），
届时只需替换 `find_blocked_words` 的实现，`check_content` 的调用方无需改动。
"""

from __future__ import annotations

import re

from app.core.exceptions import invalid_input
from app.core.logging import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# 词表（演示级最小集合）
# -----------------------------------------------------------------------------
BLOCKLIST: frozenset[str] = frozenset(
    {
        # 中文
        "炸弹",
        "赌博",
        "毒品",
        "枪支",
        "自杀",
        "色情",
        # 拉丁（匹配时不区分大小写）
        "bomb",
        "gamble",
        "cocaine",
        "porn",
    }
)

# 整条短语豁免：出现在文本中时，其内部包含的敏感词不再触发拦截
ALLOWLIST_PHRASES: frozenset[str] = frozenset(
    {
        "色情图片识别",
        "色情内容检测",
        "反赌博",
        "禁毒",
        "枪支管理法",
        "bomb detection",
        "porn detection",
    }
)

# 提示词注入特征
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 中文：忽略/忘记/无视 + （之前/上面/…）+ 指令/规则/设定
    re.compile(r"(忽略|忘记|抛弃|无视|不要理会)[^。，\n]{0,8}(指令|规则|设定|提示词|限制|要求)"),
    re.compile(r"(输出|告诉我|展示|复述|打印)[^。，\n]{0,6}(系统提示词|系统设定|你的 prompt|你的设定)"),
    # 拉丁
    re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above|preceding)\s+(instruction|prompt|rule|direction)s?",
        re.IGNORECASE,
    ),
    re.compile(r"(reveal|show|print|repeat|output)\s+your\s+(system\s+)?(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(an?\s+)?unrestricted", re.IGNORECASE),
)

# 占位符字符（不可能出现在正常输入里，用于屏蔽白名单短语）
_PLACEHOLDER = "\u0000"


def _mask_allowlisted(text: str) -> str:
    """把白名单短语替换成等长占位符，使短语内部的敏感词不会被扫到。"""
    masked = text
    for phrase in ALLOWLIST_PHRASES:
        if phrase in masked:
            masked = masked.replace(phrase, _PLACEHOLDER * len(phrase))
    return masked


def find_blocked_words(text: str) -> list[str]:
    """返回文本命中的敏感词（已去重、已应用白名单）。

    结果**仅用于日志与统计**，不返回给前端（避免泄露词表）。
    """
    if not text:
        return []

    masked = _mask_allowlisted(text).lower()
    hits: list[str] = []

    # 长词优先，保证「同一条」命中优先于其子串
    for word in sorted(BLOCKLIST, key=len, reverse=True):
        if word.lower() in masked:
            hits.append(word)

    return hits


def find_injection_patterns(text: str) -> list[str]:
    """返回命中的注入规则（便于排查，不对外返回）。"""
    if not text:
        return []
    return [p.pattern for p in INJECTION_PATTERNS if p.search(text)]


def is_blocked(text: str) -> bool:
    """文本是否应被拒绝。"""
    if not text:
        return False
    return bool(find_blocked_words(text)) or bool(find_injection_patterns(text))


def check_content(text: str) -> None:
    """内容合规检查，不合规抛 `AppError(4001)`。

    提示语刻意不包含命中的词，避免回显违规内容，也避免泄露词表。
    """
    hits = find_blocked_words(text)
    if hits:
        # 只记录命中数量与文本长度，不记录原文（原文可能违规）
        logger.warning("内容拦截：命中敏感词 %d 个，文本长度 %d", len(hits), len(text))
        raise invalid_input(
            "这个话题不太适合在这里讨论，换一个学习主题试试吧",
            detail=f"blocked_words={len(hits)}",
        )

    patterns = find_injection_patterns(text)
    if patterns:
        logger.warning("内容拦截：命中提示词注入 %d 条，文本长度 %d", len(patterns), len(text))
        raise invalid_input(
            "这句话里好像夹带了指令，换成一个正常的学习问题吧",
            detail=f"injection_patterns={len(patterns)}",
        )

    return None
