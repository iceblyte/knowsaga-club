"""极小的语种探测工具。

为什么要有它：检索的地区偏好（Tavily 的 `country`）只能由服务端决定
（它是上游的**实例级**参数），而判据只有「用户是用中文问的还是英文问的」。

刻意不做成「语言识别库」：只需要一个方向性判断，不需要精确语种。
引入一个模型或词典来回答这个问题，成本远大于收益。
"""

from __future__ import annotations

#: CJK 统一表意文字的范围。这里只认汉字 —— 日文假名与韩文谚文另有区间，
#: 而 Tavily 的 `country` 枚举里也没有对应到它们的取值。
_CJK_START = "\u4e00"
_CJK_END = "\u9fff"

#: 判定阈值。**故意定得低**：只要输入里有可观的汉字占比就按中文用户处理。
#: 理由是不对称 —— 把中文用户误判成国际用户，他会搜到一堆英文资料（直接读不了）；
#: 把英文用户误判成中文用户，`country="china"` 只是给了个倾向、并不排除英文结果。
DEFAULT_CJK_THRESHOLD = 0.10


def cjk_ratio(text: str) -> float:
    """汉字占「有意义的字符」（汉字 + 拉丁字母 + 数字）的比例。

    空白与标点不计入分母：它们既不是任何一种语言的证据，也会把比例稀释到没有区分度。
    """
    cjk = 0
    latin = 0
    for ch in text:
        if _CJK_START <= ch <= _CJK_END:
            cjk += 1
        elif ch.isascii() and ch.isalnum():
            latin += 1
    total = cjk + latin
    if total == 0:
        return 0.0
    return cjk / total


def looks_chinese(text: str, *, threshold: float = DEFAULT_CJK_THRESHOLD) -> bool:
    """输入是否应按「中文用户」处理。"""
    return cjk_ratio(text) >= threshold
