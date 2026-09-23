"""从用户输入里抽出网页链接。

## 为什么需要它

用户可以把一个网页链接直接贴进来（需求文档 P1 的「多源输入」）。这类链接
**必须被优先读**：用户把链接给你，就是明确说了「以这份资料为准」。而判据只能由
服务端算 —— 前端算出来的不能作为事实依据（它只用来决定 pill 显示哪句话）。

## 规则（与 `frontend/src/utils/links.ts` **同源**，改一处必须改另一处）

两份实现的一致性**不靠人眼比对**：判据写在 `shared/link-cases.json`，
两端各自对着同一份数据断言（后端 `tests/test_links.py`、
前端 `frontend/scripts/check_links_parity.mjs`，与 `shared/scoring-cases.json` 同一套做法）。
改规则时先改那份共享用例，再让两边同时绿。

只有两种形态算链接：

1. `http://…` / `https://…`
2. `www.…`

**不做猜测式补全**：`example.com/docs` 不算链接。理由是一句话里出现
`example.com` 太常见（它可能只是句中的域名举例），猜错的表现是「模型跑去读一个
用户没打算给的页面」，比「没识别出来」更糟 —— 后者用户会再说一遍，前者他根本不知道。

`www.` 形态会被补上 `https://` 前缀。这**不是**猜测：`www.` 开头本身就是
「这是一个网址」的声明，而 Tavily 的 extract 只接受带 scheme 的 URL。

## 为什么不复用前端的结果

前端的链接判定只用来决定大厅那只 pill 显示哪句话（4 态），是**展示**用途；
真正要读哪些页面必须由服务端独立算 —— 否则一个前端 bug 就能让「我贴了链接」变成
「服务端不知道有链接」。
"""

from __future__ import annotations

import re

#: 匹配「以 http(s):// 或 www. 开头的一段合法字符」。
#:
#: 字符集里**排除中文标点**而与空白同样对待：中文句子里 `。` 紧跟在链接后面不带空格，
#: 不排除就会把「。后面还有字」整段吞进 URL（实测如此）。中文标点不可能出现在 URL 里，
#: 排除它们是零代价的。
#:
#: ⚠️ **不能**同样排除 ASCII 的 `.` `,` `)` —— 它们在 URL 内部是合法的
#: （`?q=1,2`、`wiki/Foo_(bar)`、`v1.2`），排掉会切坏地址。它们只在**结尾**时才是标点，
#: 所以交给 `_strip_trailing` 在末尾剥。
_URL_PATTERN = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'`。，、；：！？（）【】《》「」『』\u3000]+",
    re.IGNORECASE,
)

#: 从匹配结果**尾部**剥掉、且**无需配对判断**的 ASCII 标点。
#: 出现在中间的是 URL 的一部分，所以只剥尾。
_TRAILING = ".,;:!?"

#: 需要**配对判断**才敢剥的成对符号。
#:
#: 原来 `)` 也是无脑剥的，于是 `https://en.wikipedia.org/wiki/Foo_(bar)` 会被啃掉
#: 最后一个 `)` 变成一个打不开的地址 —— 而模块 docstring 又恰好拿
#: `wiki/Foo_(bar)` 当作「不能排除 `)`」的例子，自相矛盾。
#: 现在的判据：闭合符只有在**数量多于**它的开括号时才剥
#: （`(https://a.example/p)` 尾部的 `)` 是标点，`Foo_(bar)` 尾部的是路径的一部分）。
_BRACKETS = {")": "(", "]": "[", "}": "{"}

#: `www.` 形态补的前缀。见模块 docstring。
_DEFAULT_SCHEME = "https://"


def _strip_trailing(url: str) -> str:
    """剥掉贴在链接末尾的标点。逐字符判，遇到非标点就停。"""
    while url:
        char = url[-1]
        if char in _BRACKETS:
            if url.count(char) > url.count(_BRACKETS[char]):
                url = url[:-1]
                continue
            break
        if char in _TRAILING:
            url = url[:-1]
            continue
        break
    return url


def extract_urls(text: str) -> tuple[str, ...]:
    """抽出输入里的全部链接，**去重且保序**。

    Args:
        text: 用户原始输入（已清洗或不清洗都行，本函数不依赖其他清洗步骤）。

    Returns:
        链接元组，按首次出现顺序排列。没有链接时是空元组。

    Examples:
        >>> extract_urls("帮我按 https://a.example/x 出题")
        ('https://a.example/x',)
        >>> extract_urls("看 www.a.example 和 www.a.example")
        ('https://www.a.example',)
    """
    seen: dict[str, None] = {}
    for match in _URL_PATTERN.finditer(text or ""):
        url = _strip_trailing(match.group(0))
        if not url:
            continue
        if url.lower().startswith("www."):
            url = _DEFAULT_SCHEME + url
        seen.setdefault(url, None)
    return tuple(seen)


def has_url(text: str) -> bool:
    """输入里有没有链接。前端 pill 的四态判定与本函数必须给出同一答案。"""
    return bool(extract_urls(text))


__all__ = ["extract_urls", "has_url"]
