"""文本分块的契约（`add-private-knowledge-base` 第 3 组）。

分块参数（大小 / 重叠）决定了三件事，而且**都是静默的**：

* 片段太大 → 每条的检索命中都带着大量无关内容，挤占 Prompt 的 token 预算；
* 片段太小 → 一句完整的话被腰斩，检索到的片段自己读不通；
* 重叠为 0 → 跨边界的那个知识点在两侧都不完整，永远检不到。

所以「长度上限」与「内容不丢」各有一条断言钉住，而不是靠调参试出来。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.llm.kb.splitter import build_splitter, split_text


def _settings(**over: object) -> Settings:
    """只读代码默认值的配置（断掉仓库根 `.env`）。"""
    base = Settings(_env_file=None)
    return base.model_copy(update=over) if over else base


# ---------------------------------------------------------------- 边界
def test_empty_text_yields_no_chunk() -> None:
    """空文本不产出片段 —— 一个空片段会变成一个什么都没索引的向量。"""
    assert split_text("", settings=_settings()) == []


@pytest.mark.parametrize("blank", ["   ", "\n\n\n", " \t \n  "])
def test_blank_text_yields_no_chunk(blank: str) -> None:
    """纯空白同样不产出片段。

    它比空字符串更危险：内容非空所以不会被上游的长度检查拦下，
    但入库之后是一个永不命中的向量，白占索引。
    """
    assert split_text(blank, settings=_settings()) == []


def test_short_text_stays_whole() -> None:
    """短于上限的文本只有一个片段，且内容原样保留。"""
    text = "RAG 的核心是先检索再生成。"
    chunks = split_text(text, settings=_settings(kb_chunk_size=500))

    assert len(chunks) == 1
    assert chunks[0].strip() == text


# ---------------------------------------------------------------- 长度与内容
def test_long_text_respects_chunk_size() -> None:
    """每个片段都不超过配置的长度上限。

    超限的症状不是报错，而是「每条命中都带一堆无关内容」——
    它会一路挤到出题 Prompt 的 token 预算里。
    """
    size = 120
    text = "这是一段用于测试的中文内容。" * 60  # 约 780 字
    chunks = split_text(text, settings=_settings(kb_chunk_size=size, kb_chunk_overlap=20))

    assert len(chunks) > 1
    assert max(len(c) for c in chunks) <= size


def test_long_text_loses_no_content() -> None:
    """切分不丢内容：原文里的每个非空白字符都出现在某个片段里。

    ⚠️ 这条比「片段总数够多」重要得多 —— 分块丢内容的症状是
    「这份资料里明明有这一节，出题却从来没考到」，而它不会报错。
    """
    text = "".join(f"第{i}节：这里讲的是知识块{i}的内容。" for i in range(40))
    chunks = split_text(text, settings=_settings(kb_chunk_size=100, kb_chunk_overlap=15))

    joined = "".join(chunks)
    for char in set(text.replace(" ", "")):
        assert char in joined, f"字符 {char!r} 在切分后丢失了"


def test_adjacent_chunks_overlap() -> None:
    """相邻片段有重叠 —— 跨边界的那句话不能被腰斩成两侧都不完整。"""
    text = "".join(f"语句{i}，" for i in range(80))
    chunks = split_text(text, settings=_settings(kb_chunk_size=100, kb_chunk_overlap=30))

    assert len(chunks) >= 2
    # 前一片段的尾部应当出现在后一片段的开头附近
    assert chunks[0][-10:] in chunks[1]


def test_text_without_separators_still_splits() -> None:
    """没有任何标点/换行的超长文本仍要能切。

    实际的坏例子是一长串无明显分隔的内容（加密串、无换行的表格导出）。
    它在递归切分里会一路回落到「按字符切」—— 如果那个兜底不存在，
    整段文本会变成一个远超上限的巨块。
    """
    text = "A" * 1000
    chunks = split_text(text, settings=_settings(kb_chunk_size=100, kb_chunk_overlap=10))

    assert len(chunks) > 1
    assert max(len(c) for c in chunks) <= 100


# ---------------------------------------------------------------- 配置
def test_build_splitter_rejects_overlap_not_smaller_than_size() -> None:
    """重叠必须小于片段长度。

    相等或更大时上游的切分逻辑会原地打转或产出退化结果，
    而这种配置错误在 `RecursiveCharacterTextSplitter` 里**不会**报错。
    """
    with pytest.raises(ValueError):
        build_splitter(_settings(kb_chunk_size=100, kb_chunk_overlap=100))


def test_chinese_separators_are_preferred() -> None:
    """中文标点必须在分隔符表里 —— 否则中文会被按空格切（等于按字符切）。"""
    splitter = build_splitter(_settings())

    assert "。" in splitter._separators
    assert "\n\n" in splitter._separators
