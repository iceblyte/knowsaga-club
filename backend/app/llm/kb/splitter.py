"""文本分块。

## 为什么分隔符表必须自己写

`RecursiveCharacterTextSplitter` 的默认表是 `["\\n\\n", "\\n", " ", ""]` ——
**为英文设计的**。中文句子之间没有空格，所以拿默认表切中文会一路落到最后的
「按字符切」，于是每个片段都从句子中间断掉：

    片段 1：「……监督学习的核心是学习一个映射函数，给定输入」
    片段 2：「x，输出预测值 y……」

检索命中这样的片段，模型看到的是两句半截话。它不报错，只是每次都在
「资料像是相关的但读不通」这个状态附近抖动。

## 为什么「不产出空片段」是这一层的契约

一个空片段入库之后是一个**永不命中的向量**：白占索引，还会让「本库有 N 个知识块」
这个数字对不上用户的预期。而纯空白输入（`"   "`）比空字符串更危险 ——
它内容非空，所以不会被上游的长度检查拦下。
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings

#: 分隔符优先级：从粗（段落）到细（句子）再到兜底（单字符）。
#: 中文标点在 ` ` 之前，否则中文会直接被按字符切开（见模块 docstring）。
_SEPARATORS: list[str] = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


def build_splitter(settings: Settings) -> RecursiveCharacterTextSplitter:
    """按配置构造分块器。

    Raises:
        ValueError: `kb_chunk_size` 非正，或 `kb_chunk_overlap` 不在 `[0, size)` 内。

    ⚠️ 这两种配置错误**必须在这里报**：`RecursiveCharacterTextSplitter`
    对 `overlap >= chunk_size` 不会抛异常，它只是产出一份退化的切分结果
    （片段被反复回退、或者干脆切不动），从外部完全看不出来。
    """
    size = int(settings.kb_chunk_size)
    overlap = int(settings.kb_chunk_overlap)
    if size <= 0:
        raise ValueError(f"kb_chunk_size 必须为正数，实际为 {size}")
    if overlap < 0 or overlap >= size:
        raise ValueError(
            f"kb_chunk_overlap 必须满足 0 <= overlap < chunk_size，实际为 {overlap} / {size}"
        )
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=_SEPARATORS,
        strip_whitespace=True,
    )


def split_text(text: str, *, settings: Settings) -> list[str]:
    """把一段文本切成保序的片段列表。

    Args:
        text: 已经从文件里抽取出来的纯文本。
        settings: 配置（取 `kb_chunk_size` / `kb_chunk_overlap`）。

    Returns:
        片段列表。输入为空或纯空白时返回**空列表**（不是含一个空串的列表）。
    """
    if not text or not text.strip():
        return []
    chunks = build_splitter(settings).split_text(text)
    # 再滤一道：递归切分在极端输入下可能吐出纯空白的片段
    return [chunk for chunk in chunks if chunk.strip()]
